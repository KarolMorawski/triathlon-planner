#!/usr/bin/env python3
"""
plan_review.py — Porównanie zaplanowane vs wykonane
=====================================================
Pobiera aktywności z Garmin Connect i zestawia je z zaplanowanymi
treningami. Pokazuje tygodniowy raport: co było zaplanowane, co
zostało wykonane (czas, moc, tempo) i co pominięto.

Wymaga połączenia z Garmin Connect (token w ~/.garmin_token).

Użycie:
  python3 plan_review.py --prefix WARSAW
  python3 plan_review.py --prefix WARSAW --weeks 4   # ostatnie 4 tygodnie
  python3 plan_review.py --list
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from triathlon_core import (
    STATE_DIR, TOKEN_FILE,
    validate_prefix_pl as _validate_prefix,
    load_state_pl as load_state,
    login_pl as login,
)

# Mapowanie Garmin → typ sportu planu
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


def list_plans():
    if not os.path.exists(STATE_DIR):
        print("Brak zapisanych planów.")
        return
    files = sorted(f for f in os.listdir(STATE_DIR) if f.endswith(".json"))
    today = date.today()
    print(f"Zapisane plany ({STATE_DIR}):\n")
    for fname in files:
        try:
            with open(os.path.join(STATE_DIR, fname)) as fp:
                st = json.load(fp)
            cfg = st.get("config", {})
            wkts = st.get("workouts", [])
            done = sum(1 for w in wkts if date.fromisoformat(w["date"]) < today)
            print(f"  {st['prefix']:15s}  {cfg.get('race_date')}  {cfg.get('distance'):6s}  "
                  f"wykonano={done}/{len(wkts)}")
        except Exception:
            pass



# ─── AKTYWNOŚCI GARMIN ────────────────────────────────────────────────────────

def fetch_activities(client, start_date, end_date):
    """Pobierz wszystkie aktywności w zakresie dat."""
    print(f"  Pobieranie aktywności {start_date} – {end_date}...")
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

    # Indeksuj: {(date_str, sport): activity}
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
        # Zachowaj jedną aktywność per (date, sport) — wybierz najdłuższą
        if key not in index or a.get("duration", 0) > index[key].get("duration", 0):
            index[key] = a
    print(f"  Znaleziono {len(all_acts)} aktywności ({len(index)} unikalnych powiązań)\n")
    return index


# ─── FORMAT POMOCNICZY ────────────────────────────────────────────────────────

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


# ─── RAPORT ───────────────────────────────────────────────────────────────────

def print_report(state, planned_wkts, act_index, today, show_weeks=None):
    cfg    = state["config"]
    prefix = state["prefix"]
    ftp    = cfg.get("ftp", 1)

    print(f"\n{'═'*68}")
    print(f"  PLAN REVIEW — {prefix}  ({cfg.get('race_date')}  {cfg.get('distance')})")
    print(f"{'═'*68}")

    # Grupuj zaplanowane treningi po tygodniach (poniedziałek)
    by_week = {}
    for wkt, d in planned_wkts:
        d_obj = date.fromisoformat(d)
        if d_obj > today:
            continue
        mon = d_obj - timedelta(days=d_obj.weekday())
        by_week.setdefault(mon, []).append((d_obj, wkt, d))

    if not by_week:
        print("  Brak wykonanych tygodni do przeglądu.\n")
        return

    sorted_weeks = sorted(by_week.keys())
    if show_weeks:
        sorted_weeks = sorted_weeks[-show_weeks:]

    total_planned = total_done = total_missed = 0

    for mon in sorted_weeks:
        sessions = sorted(by_week[mon], key=lambda x: x[0])
        sun = mon + timedelta(days=6)

        # Podsumowanie tygodnia
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
                lines.append(f"  {d_obj.strftime('%a %d.%m')}  {icon} ✗  {name[:38]:<38}  — pominięto")
                week_miss += 1

        week_n = (mon - sorted_weeks[0]).days // 7 + 1
        pct = week_done / (week_done + week_miss) * 100 if (week_done + week_miss) else 0
        bar = "█" * week_done + "·" * week_miss
        print(f"\n  Tydzień {week_n:2d}  ({mon.strftime('%d.%m')}–{sun.strftime('%d.%m')})  "
              f"{week_done}/{week_done+week_miss} treningów  [{bar}] {pct:.0f}%")
        for l in lines:
            print(l)

        total_planned += week_done + week_miss
        total_done    += week_done
        total_missed  += week_miss

    # Podsumowanie
    pct_overall = total_done / total_planned * 100 if total_planned else 0
    print(f"\n{'─'*68}")
    print(f"  RAZEM: {total_done}/{total_planned} treningów wykonanych  ({pct_overall:.0f}%)")
    if total_missed:
        print(f"  Pominięto: {total_missed} treningów")
    print()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Porównanie zaplanowanych i wykonanych treningów.")
    p.add_argument("--list",   action="store_true", help="Pokaż zapisane plany")
    p.add_argument("--prefix", help="Prefix planu (np. WARSAW)")
    p.add_argument("--weeks",  type=int, help="Pokaż tylko ostatnie N tygodni")
    args = p.parse_args()

    if args.list:
        list_plans()
        return
    if not args.prefix:
        p.print_help()
        return

    prefix = args.prefix.upper()
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
        from season_plan import generate_race_block
    except ImportError:
        sys.exit("BŁĄD: Brak pliku season_plan.py w bieżącym katalogu.")

    print(f"Generowanie planu {prefix}...")
    all_wkts = generate_race_block(
        race_date, distance, ftp, run_pace_ms, prefix,
        race_bike_pct=race_bike_pct, vol_scale=vol_scale
    )

    today = date.today()
    past_wkts = [(w, d) for w, d in all_wkts if date.fromisoformat(d) <= today]

    if not past_wkts:
        print("Brak wykonanych tygodni do przeglądu — plan jeszcze nie ruszył.")
        return

    plan_start = min(date.fromisoformat(d) for _, d in past_wkts)

    print("Logowanie do Garmin Connect...")
    client = login()

    act_index = fetch_activities(client, plan_start, today)
    print_report(state, past_wkts, act_index, today, show_weeks=args.weeks)


if __name__ == "__main__":
    main()
