#!/usr/bin/env python3
"""
plan_review_en.py — Planned vs actual comparison
=================================================
Fetches activities from Garmin Connect and compares them against the
training plan. Shows a weekly report: what was planned, what was done
(duration, power, pace) and what was skipped.

Requires a Garmin Connect connection (token at ~/.garmin_token).

Usage:
  python3 plan_review_en.py --prefix WARSAW
  python3 plan_review_en.py --prefix WARSAW --weeks 4   # last 4 weeks
  python3 plan_review_en.py --list
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

STATE_DIR  = os.path.expanduser("~/.triathlon_plans")
TOKEN_FILE = os.path.expanduser("~/.garmin_token")

_PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")

def _validate_prefix(p):
    """Reject prefixes that could escape STATE_DIR or contain unsafe characters."""
    if not _PREFIX_RE.match(p):
        sys.exit(f"ERROR: Invalid prefix '{p}'. Allowed: A-Z, 0-9, _, - (must start alphanumeric).")

# Garmin activity type → plan sport type mapping
GARMIN_SPORT = {
    "running":             "running",
    "trail_running":       "running",
    "treadmill_running":   "running",
    "cycling":             "cycling",
    "road_cycling":        "cycling",
    "indoor_cycling":      "cycling",
    "virtual_ride":        "cycling",
    "mountain_biking":     "cycling",
    "swimming":            "swimming",
    "lap_swimming":        "swimming",
    "open_water_swimming": "swimming",
}


# ─── STATE ────────────────────────────────────────────────────────────────────

def load_state(prefix):
    path = os.path.join(STATE_DIR, f"{prefix}.json")
    if not os.path.exists(path):
        sys.exit(
            f"ERROR: No saved plan for '{prefix}'  ({path})\n"
            f"  Run season_plan_en.py or generate_plan_en.py first."
        )
    with open(path) as f:
        return json.load(f)


def list_plans():
    if not os.path.exists(STATE_DIR):
        print("No saved plans found.")
        return
    files = sorted(f for f in os.listdir(STATE_DIR) if f.endswith(".json"))
    today = date.today()
    print(f"Saved plans ({STATE_DIR}):\n")
    for fname in files:
        try:
            with open(os.path.join(STATE_DIR, fname)) as fp:
                st = json.load(fp)
            cfg = st.get("config", {})
            wkts = st.get("workouts", [])
            done = sum(1 for w in wkts if date.fromisoformat(w["date"]) < today)
            print(f"  {st['prefix']:15s}  {cfg.get('race_date')}  {cfg.get('distance'):6s}  "
                  f"done={done}/{len(wkts)}")
        except Exception:
            pass


# ─── GARMIN LOGIN ─────────────────────────────────────────────────────────────

def login():
    try:
        from garminconnect import Garmin
    except ImportError:
        sys.exit("ERROR: garminconnect not installed.\n  pip install garminconnect")
    import getpass
    if os.path.isfile(TOKEN_FILE):
        try:
            client = Garmin()
            with open(TOKEN_FILE) as f:
                client.login(tokenstore=f.read())
            print("✓ Logged in to Garmin Connect (cached token)\n")
            return client
        except Exception:
            print("  Cached token expired — fresh login required.")
    email    = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")
    client   = Garmin(email=email, password=password, return_on_mfa=True)
    result, state = client.login()
    if result == "needs_mfa":
        client.resume_login(state, input("MFA code: ").strip())
    with open(TOKEN_FILE, "w") as f:
        f.write(client.client.dumps())
    os.chmod(TOKEN_FILE, 0o600)
    return client


# ─── GARMIN ACTIVITIES ────────────────────────────────────────────────────────

def fetch_activities(client, start_date, end_date):
    """Fetch all activities in the date range."""
    print(f"  Fetching activities {start_date} – {end_date}...")
    all_acts = []
    start = 0
    limit = 100
    while True:
        batch = client.get_activities(start=start, limit=limit)
        if not batch:
            break
        filtered = []
        stop = False
        for a in batch:
            raw = a.get("startTimeLocal") or a.get("startTimeGMT") or ""
            d = raw[:10]
            if not d:
                continue
            try:
                act_date = date.fromisoformat(d)
            except ValueError:
                continue
            if act_date < start_date:
                stop = True
                break
            if act_date <= end_date:
                filtered.append(a)
        all_acts.extend(filtered)
        if stop or len(batch) < limit:
            break
        start += limit
        time.sleep(0.3)

    # Index: {(date_str, sport): activity}
    index = {}
    for a in all_acts:
        raw  = (a.get("startTimeLocal") or a.get("startTimeGMT") or "")[:10]
        atype = (a.get("activityType") or {})
        if isinstance(atype, dict):
            type_key = atype.get("typeKey", "")
        else:
            type_key = str(atype)
        sport = GARMIN_SPORT.get(type_key, type_key)
        key   = (raw, sport)
        # Keep one activity per (date, sport) — choose the longest
        if key not in index or a.get("duration", 0) > index[key].get("duration", 0):
            index[key] = a
    print(f"  Found {len(all_acts)} activities ({len(index)} unique matches)\n")
    return index


# ─── FORMAT HELPERS ───────────────────────────────────────────────────────────

def _fmt_dur(secs):
    if not secs:
        return "—"
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_pace(speed_ms):
    if not speed_ms or speed_ms <= 0:
        return "—"
    spk = 1000.0 / speed_ms
    return f"{int(spk//60)}:{int(spk%60):02d}/km"


def _fmt_power(watts):
    if not watts or watts <= 0:
        return "—"
    return f"{int(watts)}W"


def _sport_icon(sport):
    return {"running": "🏃", "cycling": "🚲", "swimming": "🏊"}.get(sport, "●")


# ─── REPORT ───────────────────────────────────────────────────────────────────

def print_report(state, planned_wkts, act_index, today, show_weeks=None):
    cfg    = state["config"]
    prefix = state["prefix"]
    ftp    = cfg.get("ftp", 1)

    print(f"\n{'═'*68}")
    print(f"  PLAN REVIEW — {prefix}  ({cfg.get('race_date')}  {cfg.get('distance')})")
    print(f"{'═'*68}")

    by_week = {}
    for wkt, d in planned_wkts:
        d_obj = date.fromisoformat(d)
        if d_obj > today:
            continue
        mon = d_obj - timedelta(days=d_obj.weekday())
        by_week.setdefault(mon, []).append((d_obj, wkt, d))

    if not by_week:
        print("  No completed weeks to review.\n")
        return

    sorted_weeks = sorted(by_week.keys())
    if show_weeks:
        sorted_weeks = sorted_weeks[-show_weeks:]

    total_planned = total_done = total_missed = 0

    for mon in sorted_weeks:
        sessions = sorted(by_week[mon], key=lambda x: x[0])
        sun = mon + timedelta(days=6)

        week_done = week_miss = 0
        lines = []
        for d_obj, wkt, d_str in sessions:
            sport = wkt["sportType"]["sportTypeKey"]
            name  = wkt["workoutName"]
            icon  = _sport_icon(sport)

            act = act_index.get((d_str, sport))

            if act:
                dur      = act.get("duration") or act.get("movingDuration") or 0
                speed    = act.get("averageSpeed") or 0
                power    = act.get("averagePower") or 0
                dist_m   = act.get("distance") or 0

                if sport == "cycling":
                    perf = f"{_fmt_dur(dur)}  {_fmt_power(power)}"
                    if power and ftp:
                        perf += f"  ({power/ftp*100:.0f}% FTP)"
                elif sport == "running":
                    perf = f"{_fmt_dur(dur)}  {_fmt_pace(speed)}"
                else:
                    perf = f"{_fmt_dur(dur)}  {dist_m/1000:.1f}km"

                lines.append(f"  {d_obj.strftime('%a %d.%m')}  {icon} ✓  {name[:38]:<38}  {perf}")
                week_done += 1
            else:
                lines.append(f"  {d_obj.strftime('%a %d.%m')}  {icon} ✗  {name[:38]:<38}  — skipped")
                week_miss += 1

        week_n = (mon - sorted_weeks[0]).days // 7 + 1
        pct = week_done / (week_done + week_miss) * 100 if (week_done + week_miss) else 0
        bar = "█" * week_done + "·" * week_miss
        print(f"\n  Week {week_n:2d}  ({mon.strftime('%d.%m')}–{sun.strftime('%d.%m')})  "
              f"{week_done}/{week_done+week_miss} workouts  [{bar}] {pct:.0f}%")
        for l in lines:
            print(l)

        total_planned += week_done + week_miss
        total_done    += week_done
        total_missed  += week_miss

    pct_overall = total_done / total_planned * 100 if total_planned else 0
    print(f"\n{'─'*68}")
    print(f"  TOTAL: {total_done}/{total_planned} workouts completed  ({pct_overall:.0f}%)")
    if total_missed:
        print(f"  Skipped: {total_missed} workouts")
    print()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Compare planned vs actual workouts.")
    p.add_argument("--list",   action="store_true", help="List all saved plans")
    p.add_argument("--prefix", help="Plan prefix (e.g. WARSAW)")
    p.add_argument("--weeks",  type=int, help="Show only last N weeks")
    args = p.parse_args()

    if args.list:
        list_plans()
        return
    if not args.prefix:
        p.print_help()
        return

    prefix = prefix
    _validate_prefix(prefix)
    state = load_state(prefix)
    cfg   = state["config"]

    ftp           = cfg["ftp"]
    run_pace_ms   = cfg.get("run_pace_ms")
    race_date     = date.fromisoformat(cfg["race_date"])
    distance      = cfg["distance"]
    vol_scale     = cfg.get("vol_scale", 1.0)
    race_bike_pct = cfg.get("race_bike_pct")

    if not run_pace_ms and cfg.get("run_pace_str"):
        parts = cfg["run_pace_str"].split(":")
        run_pace_ms = 1000.0 / (int(parts[0]) * 60 + int(parts[1]))

    try:
        from season_plan_en import generate_race_block
    except ImportError:
        sys.exit("ERROR: season_plan_en.py not found in current directory.")

    print(f"Generating plan {prefix}...")
    all_wkts = generate_race_block(
        race_date, distance, ftp, run_pace_ms, prefix,
        race_bike_pct=race_bike_pct, vol_scale=vol_scale
    )

    today = date.today()
    past_wkts = [(w, d) for w, d in all_wkts if date.fromisoformat(d) <= today]

    if not past_wkts:
        print("No completed weeks to review — plan has not started yet.")
        return

    plan_start = min(date.fromisoformat(d) for _, d in past_wkts)

    print("Logging in to Garmin Connect...")
    client = login()

    act_index = fetch_activities(client, plan_start, today)
    print_report(state, past_wkts, act_index, today, show_weeks=args.weeks)


if __name__ == "__main__":
    main()
