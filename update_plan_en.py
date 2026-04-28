#!/usr/bin/env python3
"""
update_plan_en.py — Update an existing triathlon training plan
==============================================================
Loads a saved plan state (~/.triathlon_plans/{PREFIX}.json),
shows progress, accepts new parameters (or pulls them from Strava),
and replaces future workouts with updated ones.

Usage:
  python3 update_plan_en.py --list
  python3 update_plan_en.py --prefix WARSAW
  python3 update_plan_en.py --prefix WARSAW --ftp 265 --vol-scale 1.1
  python3 update_plan_en.py --prefix WARSAW --target-time 5:10:00
  python3 update_plan_en.py --prefix WARSAW --from-strava
  python3 update_plan_en.py --prefix WARSAW --from-strava --dry-run
  python3 update_plan_en.py --prefix WARSAW --from-date 2026-07-01 --ftp 270
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, timedelta

STATE_DIR = os.path.expanduser("~/.triathlon_plans")

_PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")

def _validate_prefix(p):
    """Reject prefixes that could escape STATE_DIR or contain unsafe characters."""
    if not _PREFIX_RE.match(p):
        sys.exit(f"ERROR: Invalid prefix '{p}'. Allowed: A-Z, 0-9, _, - (must start alphanumeric).")


# ─── STATE I/O ────────────────────────────────────────────────────────────────

def load_state(prefix):
    path = os.path.join(STATE_DIR, f"{prefix}.json")
    if not os.path.exists(path):
        sys.exit(
            f"ERROR: No saved plan for prefix '{prefix}'\n"
            f"  Expected: {path}\n"
            f"  Run season_plan_en.py or generate_plan_en.py first to create a plan."
        )
    with open(path) as f:
        return json.load(f)


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{state['prefix']}.json")
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  State saved → {path}")


# ─── LISTING ──────────────────────────────────────────────────────────────────

def list_plans():
    if not os.path.exists(STATE_DIR):
        print("No saved plans found.")
        return
    files = sorted(f for f in os.listdir(STATE_DIR) if f.endswith(".json"))
    if not files:
        print("No saved plans found.")
        return
    today = date.today()
    print(f"Saved plans ({STATE_DIR}):\n")
    for fname in files:
        try:
            with open(os.path.join(STATE_DIR, fname)) as fp:
                st = json.load(fp)
            cfg = st.get("config", {})
            wkts = st.get("workouts", [])
            done   = sum(1 for w in wkts if date.fromisoformat(w["date"]) < today)
            remain = len(wkts) - done
            updated = f"  updated {st['updated_at']}" if st.get("updated_at") else ""
            print(f"  {st['prefix']:15s}  {cfg.get('race_date')}  {cfg.get('distance'):6s}  "
                  f"ftp={cfg.get('ftp')}W  "
                  f"done={done}  remaining={remain}  "
                  f"(generated {st.get('generated_at')}{updated})")
        except Exception as e:
            print(f"  {fname}  [read error: {e}]")


# ─── STATUS ───────────────────────────────────────────────────────────────────

def show_status(state, today=None):
    today = today or date.today()
    workouts = state.get("workouts", [])
    cfg = state["config"]

    def week_range(wlist):
        nums = set()
        for w in wlist:
            try:
                nums.add(int(w["name"].split("-T")[1][:2]))
            except (IndexError, ValueError):
                pass
        if not nums:
            return "—"
        lo, hi = min(nums), max(nums)
        return f"weeks {lo}–{hi}" if lo != hi else f"week {lo}"

    past   = [w for w in workouts if date.fromisoformat(w["date"]) < today]
    future = [w for w in workouts if date.fromisoformat(w["date"]) >= today]

    print(f"\n{'═'*55}")
    print(f"  PLAN: {state['prefix']}  ({cfg.get('race_date')}  {cfg.get('distance')})")
    print(f"{'═'*55}")
    print(f"  Generated:  {state.get('generated_at')}")
    if state.get("updated_at"):
        print(f"  Updated:    {state['updated_at']}")
    print(f"  FTP:        {cfg.get('ftp')}W  |  Weight: {cfg.get('weight_kg')}kg")
    if cfg.get("target_time"):
        print(f"  Target:     {cfg['target_time']}")
    if cfg.get("run_pace_str"):
        print(f"  Run pace:   {cfg['run_pace_str']}/km")
    if cfg.get("vol_scale", 1.0) != 1.0:
        print(f"  Vol scale:  {cfg['vol_scale']}")
    print()

    if past:
        print(f"  Completed:  {len(past):3d} workouts  ({week_range(past)})")
    if future:
        print(f"  Remaining:  {len(future):3d} workouts  ({week_range(future)})")
        nxt_date = min(w["date"] for w in future)
        nxt_name = next(w["name"] for w in future if w["date"] == nxt_date)
        print(f"  Next:       {nxt_date}  {nxt_name}")
    elif not past:
        print("  No workouts recorded.")

    return past, future


# ─── GARMIN DELETE ────────────────────────────────────────────────────────────

def clean_future(client, state, cutoff):
    """Remove schedule entries and library workouts dated >= cutoff."""
    http = client.client
    prefix = state["prefix"]

    future_ids = {
        w["workout_id"] for w in state["workouts"]
        if w.get("workout_id") and date.fromisoformat(w["date"]) >= cutoff
    }
    if not future_ids:
        print("  No future workouts in state to remove.")
        return

    # Remove schedule entries from calendar
    print(f"  Clearing calendar entries from {cutoff}...")
    today = date.today()
    removed_s = 0
    for dm in range(0, 14):
        y = today.year + (today.month + dm - 1) // 12
        m = (today.month + dm - 1) % 12
        try:
            data = client.connectapi(f"/calendar-service/year/{y}/month/{m}")
            for item in data.get("calendarItems", []):
                if item.get("itemType") != "workout":
                    continue
                if not item.get("title", "").startswith(prefix):
                    continue
                raw = item.get("date") or item.get("startDate") or ""
                try:
                    if date.fromisoformat(raw[:10]) < cutoff:
                        continue
                except ValueError:
                    pass
                sid = item.get("id") or item.get("scheduleId")
                if sid:
                    try:
                        http.request("DELETE", "connectapi",
                                     f"/workout-service/schedule/{sid}", api=True)
                        removed_s += 1
                        time.sleep(0.08)
                    except Exception:
                        pass
        except Exception:
            pass
    print(f"    {removed_s} schedule entries removed")

    # Remove library workouts
    print(f"  Removing {len(future_ids)} library workouts...")
    removed_l = 0
    for wid in future_ids:
        try:
            http.request("DELETE", "connectapi",
                         f"/workout-service/workout/{wid}", api=True)
            removed_l += 1
            time.sleep(0.08)
        except Exception:
            pass
    print(f"    {removed_l} library workouts removed")


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _next_monday():
    today = date.today()
    days = (7 - today.weekday()) % 7 or 7
    return today + timedelta(days=days)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Update a triathlon training plan with new parameters.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python3 update_plan_en.py --list
  python3 update_plan_en.py --prefix WARSAW
  python3 update_plan_en.py --prefix WARSAW --ftp 265 --vol-scale 1.1
  python3 update_plan_en.py --prefix WARSAW --target-time 5:10:00
  python3 update_plan_en.py --prefix WARSAW --from-strava
  python3 update_plan_en.py --prefix WARSAW --from-strava --dry-run
  python3 update_plan_en.py --prefix WARSAW --from-date 2026-07-14 --ftp 270
""")
    p.add_argument("--list",        action="store_true", help="List all saved plans")
    p.add_argument("--prefix",      help="Plan prefix to update (e.g. WARSAW)")
    p.add_argument("--ftp",         type=int,   help="New FTP in watts")
    p.add_argument("--run-pace",    help="New race run pace MM:SS/km")
    p.add_argument("--target-time", help="New target finish time H:MM:SS")
    p.add_argument("--vol-scale",   type=float, help="New volume multiplier (0.5–1.5)")
    p.add_argument("--weight",      type=float, help="New body weight kg")
    p.add_argument("--from-strava", action="store_true",
                   help="Pull Strava suggestions before updating")
    p.add_argument("--from-date",   help="Update workouts from date YYYY-MM-DD "
                                         "(default: next Monday)")
    p.add_argument("--dry-run",     action="store_true",
                   help="Preview changes without uploading to Garmin")
    args = p.parse_args()

    if args.ftp is not None and args.ftp <= 0:
        p.error(f"--ftp must be > 0 (got {args.ftp})")
    if args.weight is not None and args.weight <= 0:
        p.error(f"--weight must be > 0 (got {args.weight})")
    if args.vol_scale is not None and not (0.1 <= args.vol_scale <= 3.0):
        p.error(f"--vol-scale must be in [0.1, 3.0] (got {args.vol_scale})")

    if args.list:
        list_plans()
        return

    if not args.prefix:
        p.print_help()
        return

    prefix = args.prefix.upper()
    _validate_prefix(prefix)
    state = load_state(prefix)
    today = date.today()
    past, future = show_status(state, today)

    if not future:
        print("\nNo future workouts — plan is complete or all in the past.")
        return

    cfg = dict(state["config"])

    # Cutoff date
    cutoff = date.fromisoformat(args.from_date) if args.from_date else _next_monday()
    in_scope = [w for w in future if date.fromisoformat(w["date"]) >= cutoff]
    print(f"\n  Update from: {cutoff}  ({len(in_scope)} workouts to replace)\n")

    # Strava suggestions
    if args.from_strava:
        try:
            from strava_suggest import _get_token, fetch_activities, analyze, suggest, print_report
            print("  Connecting to Strava...")
            token = _get_token()
            acts  = fetch_activities(token, weeks=4)
            stats = analyze(acts, 4)
            sug   = suggest(cfg["distance"], stats)
            print_report(cfg["distance"], cfg.get("race_date"), 4, stats, sug)
            if args.vol_scale is None and sug.get("vol_scale"):
                args.vol_scale = sug["vol_scale"]
            if not args.target_time and sug.get("target_time"):
                args.target_time = sug["target_time"]
            if not args.run_pace and not args.target_time:
                rp = sug.get("run_pace_race", "—")
                if rp not in ("—", "", None):
                    args.run_pace = rp.replace("/km", "").strip()
        except Exception as e:
            print(f"  ⚠ Strava unavailable: {e}")

    # Apply overrides
    if args.ftp:                       cfg["ftp"]          = args.ftp
    if args.weight:                    cfg["weight_kg"]    = args.weight
    if args.vol_scale is not None:     cfg["vol_scale"]    = args.vol_scale
    if args.target_time:
        cfg["target_time"] = args.target_time
        cfg.pop("run_pace_str", None)
    elif args.run_pace:
        cfg["run_pace_str"] = args.run_pace
        cfg.pop("target_time", None)

    # Show new parameters
    print(f"  {'─'*50}")
    print(f"  New parameters for updated weeks:")
    print(f"    FTP:       {cfg['ftp']}W")
    print(f"    Vol scale: {cfg.get('vol_scale', 1.0)}")
    if cfg.get("target_time"):
        print(f"    Target:    {cfg['target_time']}")
    elif cfg.get("run_pace_str"):
        print(f"    Run pace:  {cfg['run_pace_str']}/km")
    print(f"  {'─'*50}\n")

    # Import plan generation logic
    try:
        from season_plan_en import (generate_race_block, calc_splits,
                                     pace_to_ms, ms_to_pace, login, upload_workouts)
    except ImportError:
        sys.exit("ERROR: season_plan_en.py not found in current directory.")

    ftp       = cfg["ftp"]
    weight_kg = cfg.get("weight_kg", 75)
    cda       = cfg.get("cda", 0.32)
    vol_scale = cfg.get("vol_scale", 1.0)
    race_date = date.fromisoformat(cfg["race_date"])
    distance  = cfg["distance"]
    prefix    = state["prefix"]

    # Resolve run pace and bike zone
    race_bike_pct = None
    if cfg.get("target_time"):
        try:
            splits = calc_splits(distance, cfg["target_time"], ftp, weight_kg, cda)
            run_pace_ms   = splits["run_pace_ms"]
            race_bike_pct = splits["bike_pct_ftp"]
            cfg["run_pace_str"] = ms_to_pace(run_pace_ms)
            cfg["run_pace_ms"]  = run_pace_ms
            print(f"  Splits from {cfg['target_time']}:  "
                  f"run {splits['run_pace_str']}/km  "
                  f"bike ~{splits['bike_watts']}W ({splits['bike_pct_ftp']*100:.0f}% FTP)\n")
        except Exception as e:
            print(f"  ⚠ calc_splits: {e} — using saved pace.")
            run_pace_ms = cfg.get("run_pace_ms") or pace_to_ms(cfg.get("run_pace_str", "5:30"))
    elif cfg.get("run_pace_str"):
        run_pace_ms = pace_to_ms(cfg["run_pace_str"])
        cfg["run_pace_ms"] = run_pace_ms
    else:
        sys.exit("ERROR: No run pace or target time. Provide --run-pace or --target-time.")

    # Generate full plan, keep only workouts from cutoff onwards
    all_wkts  = generate_race_block(race_date, distance, ftp, run_pace_ms, prefix,
                                    race_bike_pct=race_bike_pct, vol_scale=vol_scale)
    new_wkts  = [(w, d) for w, d in all_wkts if date.fromisoformat(d) >= cutoff]

    print(f"  Workouts to upload: {len(new_wkts)}")

    # Predicted race day TSB (requires training_load.py in directory)
    try:
        from training_load import estimate_tss, compute_load
    except ImportError:
        estimate_tss = compute_load = None
    if estimate_tss and compute_load:
        from datetime import timedelta as _td
        daily_tss = {}
        for wkt, d in all_wkts:
            tss = estimate_tss(wkt, ftp, run_pace_ms)
            daily_tss[d] = daily_tss.get(d, 0.0) + tss
        _weeks = {"sprint": 8, "olympic": 10, "70.3": 12, "full": 16}
        plan_start = race_date - _td(weeks=_weeks[distance])
        pmc_start  = plan_start - _td(weeks=6)
        pmc = compute_load(daily_tss, pmc_start, race_date)
        rp  = pmc.get(race_date, {})
        tsb, ctl = rp.get("tsb", 0), rp.get("ctl", 0)
        if tsb < 5:
            taper_date = (_next_monday() + _td(weeks=1)).isoformat()
            print(f"\n  ⚠ Predicted race day TSB: {tsb:+.1f}  CTL: {ctl:.0f}")
            print(f"    Too low (target: 5–25). Consider a longer taper:")
            print(f"    re-run with --from-date {taper_date} (one week earlier)\n")
        elif tsb > 25:
            taper_date = (_next_monday() - _td(weeks=1)).isoformat()
            print(f"\n  ⚠ Predicted race day TSB: {tsb:+.1f}  CTL: {ctl:.0f}")
            print(f"    Too high (target: 5–25). Consider a shorter taper:")
            print(f"    re-run with --from-date {taper_date} (one week later)\n")
        else:
            print(f"\n  ✓ Predicted race day TSB: {tsb:+.1f}  CTL: {ctl:.0f}  — on target\n")

    if args.dry_run:
        print("\n  DRY RUN — future workouts after update:\n")
        for wkt, d in sorted(new_wkts, key=lambda x: x[1]):
            sp = wkt["sportType"]["sportTypeKey"][0].upper()
            print(f"    {d}  [{sp}] {wkt['workoutName']}")
        print(f"\n  (No changes made)\n")
        return

    if not new_wkts:
        print("  Nothing to upload.")
        return

    confirm = input(
        f"\nDelete {len(in_scope)} existing future workouts and upload "
        f"{len(new_wkts)} new ones? (yes/no): "
    ).strip().lower()
    if confirm not in ("yes", "y", "tak"):
        print("Aborted.")
        return

    print("\nLogging in to Garmin Connect...")
    client = login()

    print(f"\nRemoving future workouts from {cutoff}...")
    clean_future(client, state, cutoff)

    print(f"\nUploading {len(new_wkts)} workouts...")
    ok, fail, uploaded = upload_workouts(client, new_wkts)
    print(f"  ✓ Uploaded: {ok}" + (f" | Errors: {fail}" if fail else ""))

    # Keep past, replace future
    kept = [w for w in state["workouts"] if date.fromisoformat(w["date"]) < cutoff]
    state["workouts"]   = kept + uploaded
    state["config"]     = cfg
    state["updated_at"] = date.today().isoformat()

    save_state(state)
    print(f"\n  Plan updated. View at: https://connect.garmin.com/app/calendar\n")


if __name__ == "__main__":
    main()
