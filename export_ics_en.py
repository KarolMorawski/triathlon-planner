#!/usr/bin/env python3
"""
export_ics_en.py — Export training plan to calendar (.ics)
==========================================================
Generates an iCalendar file with all scheduled workouts.
Import the file into Google Calendar, Apple Calendar, or Outlook.

Requires a saved plan state (~/.triathlon_plans/{PREFIX}.json).

Usage:
  python3 export_ics_en.py --prefix WARSAW
  python3 export_ics_en.py --prefix WARSAW --output my_plan.ics
  python3 export_ics_en.py --prefix WARSAW --future-only
  python3 export_ics_en.py --list
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

STATE_DIR = os.path.expanduser("~/.triathlon_plans")

SPORT_ICON  = {"running": "🏃", "cycling": "🚲", "swimming": "🏊"}
SPORT_LABEL = {"running": "Run", "cycling": "Bike", "swimming": "Swim"}


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
            print(f"  {st['prefix']:15s}  {cfg.get('race_date')}  "
                  f"{cfg.get('distance'):6s}  done={done}/{len(wkts)}")
        except Exception:
            pass


# ─── ICS ──────────────────────────────────────────────────────────────────────

def _esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

def _ics_date(d):
    return d.strftime("%Y%m%d")


def generate_ics(state, workouts, prefix):
    cfg = state["config"]
    race_date = date.fromisoformat(cfg["race_date"])

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//Triathlon Planner//{prefix}//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:" + _esc(f"Triathlon — {prefix}"),
        "X-WR-CALDESC:" + _esc(
            f"Training plan {cfg.get('distance','').upper()} · "
            f"race {cfg.get('race_date')} · FTP {cfg.get('ftp')}W"
        ),
    ]

    for wkt, d_str in sorted(workouts, key=lambda x: x[1]):
        d_obj    = date.fromisoformat(d_str)
        sport    = wkt["sportType"]["sportTypeKey"]
        name     = wkt["workoutName"]
        icon     = SPORT_ICON.get(sport, "●")
        label    = SPORT_LABEL.get(sport, sport)

        dtstart = _ics_date(d_obj)
        dtend   = _ics_date(d_obj + timedelta(days=1))
        uid     = f"{prefix}-{d_str}-{sport[:3].upper()}@triathlon-planner"

        desc_parts = [label]
        if sport == "cycling" and cfg.get("ftp"):
            desc_parts.append(f"FTP: {cfg['ftp']}W")
        elif sport == "running" and cfg.get("run_pace_str"):
            desc_parts.append(f"Pace: {cfg['run_pace_str']}/km")
        if d_obj == race_date:
            desc_parts.append("RACE DAY 🏁")
        description = " · ".join(desc_parts)

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;VALUE=DATE:{dtstart}",
            f"DTEND;VALUE=DATE:{dtend}",
            f"SUMMARY:{icon} {_esc(name)}",
            f"DESCRIPTION:{_esc(description)}",
            f"CATEGORIES:{label.upper()}",
            "END:VEVENT",
        ]

    lines += [
        "BEGIN:VEVENT",
        f"UID:{prefix}-RACE-{cfg['race_date']}@triathlon-planner",
        f"DTSTART;VALUE=DATE:{_ics_date(race_date)}",
        f"DTEND;VALUE=DATE:{_ics_date(race_date + timedelta(days=1))}",
        f"SUMMARY:🏁 RACE — {prefix} ({cfg.get('distance','').upper()})",
        "DESCRIPTION:" + _esc(f"Target: {cfg.get('target_time','—')}  FTP: {cfg.get('ftp')}W"),
        "CATEGORIES:RACE",
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    return "\r\n".join(lines)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Export training plan to .ics (Google/Apple/Outlook calendar).")
    p.add_argument("--list",        action="store_true", help="List all saved plans")
    p.add_argument("--prefix",      help="Plan prefix (e.g. WARSAW)")
    p.add_argument("--output",      help="Output filename (default: {PREFIX}.ics)")
    p.add_argument("--future-only", action="store_true",
                   help="Export only future workouts")
    args = p.parse_args()

    if args.list:
        list_plans()
        return
    if not args.prefix:
        p.print_help()
        return

    state  = load_state(args.prefix.upper())
    cfg    = state["config"]
    prefix = state["prefix"]

    ftp          = cfg["ftp"]
    run_pace_ms  = cfg.get("run_pace_ms")
    race_date    = date.fromisoformat(cfg["race_date"])
    distance     = cfg["distance"]
    vol_scale    = cfg.get("vol_scale", 1.0)
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
    if args.future_only:
        workouts = [(w, d) for w, d in all_wkts if date.fromisoformat(d) >= today]
        print(f"Exporting: {len(workouts)} future workouts")
    else:
        workouts = all_wkts
        print(f"Exporting: {len(workouts)} workouts (full plan)")

    ics_content = generate_ics(state, workouts, prefix)

    out_path = args.output or f"{prefix}.ics"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(ics_content)

    print(f"\n  ✓ Saved: {out_path}  ({len(workouts)} workouts)\n")
    print(f"  How to import:")
    print(f"    Google Calendar:  calendar.google.com → Other calendars → Import")
    print(f"    Apple Calendar:   File → Import → select {out_path}")
    print(f"    Outlook:          File → Open & Export → Import/Export\n")


if __name__ == "__main__":
    main()
