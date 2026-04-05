#!/usr/bin/env python3
"""
Triathlon Training Plan Generator for Garmin Connect
=====================================================
Generates a complete training plan based on race date and distance.
Uploads all workouts to Garmin Connect with correct power/pace targets.

Usage:
  python3 generate_plan.py
  python3 generate_plan.py --race-date 2026-09-15 --distance 70.3 --ftp 250 --run-pace 5:20 --weight 80
  python3 generate_plan.py --reset  (full reset before uploading)

Supported distances: 70.3 (Half Ironman), full (Ironman), olympic, sprint
"""

import argparse
import sys
import time
import math
import getpass
from datetime import date, timedelta
from collections import defaultdict

# ─── GARMIN CONNECTION ───────────────────────────────────────────────────────

def login():
    try:
        from garminconnect import Garmin
    except ImportError:
        print("ERROR: garminconnect not installed.")
        print("Run: pip install garminconnect")
        sys.exit(1)

    email    = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")
    client   = Garmin(email=email, password=password)
    try:
        client.login()
    except Exception as e:
        msg = str(e)
        if any(x in msg for x in ["MFA", "2FA", "OTP", "code"]):
            client.login(mfa_code=input("MFA/2FA code: ").strip())
        else:
            raise
    print("✓ Logged in to Garmin Connect\n")
    return client

def _get_http(client):
    return getattr(client, "garth", None) or getattr(client, "client", None)

# ─── DISTANCE PROFILES ───────────────────────────────────────────────────────

PROFILES = {
    "70.3": {
        "swim_m": 1900, "bike_km": 90,  "run_km": 21.1, "weeks": 12,
        "label": "Half Ironman 70.3",
        "race_pace_pct": 0.82,  # % FTP for bike
    },
    "full": {
        "swim_m": 3800, "bike_km": 180, "run_km": 42.2, "weeks": 16,
        "label": "Full Ironman",
        "race_pace_pct": 0.72,
    },
    "olympic": {
        "swim_m": 1500, "bike_km": 40,  "run_km": 10,   "weeks": 10,
        "label": "Olympic Distance",
        "race_pace_pct": 0.88,
    },
    "sprint": {
        "swim_m": 750,  "bike_km": 20,  "run_km": 5,    "weeks": 8,
        "label": "Sprint Distance",
        "race_pace_pct": 0.95,
    },
}

# ─── SPORT TYPES ─────────────────────────────────────────────────────────────

def sport(key):
    return {
        "run":  {"sportTypeId": 1, "sportTypeKey": "running",  "displayOrder": 1},
        "bike": {"sportTypeId": 2, "sportTypeKey": "cycling",  "displayOrder": 2},
        "swim": {"sportTypeId": 4, "sportTypeKey": "swimming", "displayOrder": 4},
    }[key]

# ─── STEP BUILDERS ───────────────────────────────────────────────────────────

def _no_target():
    return {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}

def _power_target(lo_w, hi_w):
    # CONFIRMED: workoutTargetTypeId=2 + power.zone = absolute watts in Garmin API
    return {"workoutTargetTypeId": 2, "workoutTargetTypeKey": "power.zone", "displayOrder": 2}

def _hr_target(lo_bpm, hi_bpm):
    return {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}

def _pace_target(lo_ms, hi_ms):
    # pace in m/s  (Garmin stores as m/s, displays as min/km)
    return {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}

def _bike_step(order, type_id, type_key, mins, target_type, v1=None, v2=None):
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": type_id, "stepTypeKey": type_key, "displayOrder": type_id},
        "childStepId": None,
        "description": None,
        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time",
                         "displayOrder": 2, "displayable": True},
        "endConditionValue": float(mins * 60),
        "targetType": target_type,
        "targetValueOne": v1,
        "targetValueTwo": v2,
        "targetValueUnit": None,
        "zoneNumber": None,
        "secondaryTargetType": None,
        "secondaryTargetValueOne": None,
        "secondaryTargetValueTwo": None,
        "secondaryTargetValueUnit": None,
        "secondaryZoneNumber": None,
        "strokeType": None,
        "equipmentType": None,
    }

def _run_step(order, type_id, type_key, mins=None, dist_m=None,
              target_type=None, v1=None, v2=None):
    if dist_m:
        end_cond = {"conditionTypeId": 3, "conditionTypeKey": "distance",
                    "displayOrder": 3, "displayable": True}
        end_val = float(dist_m)
    else:
        end_cond = {"conditionTypeId": 2, "conditionTypeKey": "time",
                    "displayOrder": 2, "displayable": True}
        end_val = float(mins * 60)
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": type_id, "stepTypeKey": type_key, "displayOrder": type_id},
        "childStepId": None,
        "description": None,
        "endCondition": end_cond,
        "endConditionValue": end_val,
        "targetType": target_type or _no_target(),
        "targetValueOne": v1,
        "targetValueTwo": v2,
        "targetValueUnit": None,
        "zoneNumber": None,
        "secondaryTargetType": None,
        "secondaryTargetValueOne": None,
        "secondaryTargetValueTwo": None,
        "secondaryTargetValueUnit": None,
        "secondaryZoneNumber": None,
        "strokeType": None,
        "equipmentType": None,
    }

def _swim_step(order, type_id, type_key, dist_m, target_type=None, v1=None, v2=None):
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": type_id, "stepTypeKey": type_key, "displayOrder": type_id},
        "childStepId": None,
        "description": None,
        "endCondition": {"conditionTypeId": 3, "conditionTypeKey": "distance",
                         "displayOrder": 3, "displayable": True},
        "endConditionValue": float(dist_m),
        "targetType": target_type or _no_target(),
        "targetValueOne": v1,
        "targetValueTwo": v2,
        "targetValueUnit": None,
        "zoneNumber": None,
        "secondaryTargetType": None,
        "secondaryTargetValueOne": None,
        "secondaryTargetValueTwo": None,
        "secondaryTargetValueUnit": None,
        "secondaryZoneNumber": None,
        "strokeType": {"strokeTypeId": 0, "strokeTypeKey": None, "displayOrder": 0},
        "equipmentType": {"equipmentTypeId": 0, "equipmentTypeKey": None, "displayOrder": 0},
    }

# ─── PACE CONVERSION ─────────────────────────────────────────────────────────

def pace_to_ms(pace_str):
    """Convert 'M:SS' or 'MM:SS' pace per km to m/s"""
    parts = pace_str.strip().split(":")
    mins, secs = int(parts[0]), int(parts[1])
    sec_per_km = mins * 60 + secs
    return 1000.0 / sec_per_km  # m/s

def ms_to_pace(ms):
    """Convert m/s to pace string MM:SS/km"""
    sec_per_km = 1000.0 / ms
    m = int(sec_per_km // 60)
    s = int(sec_per_km % 60)
    return f"{m}:{s:02d}"

# ─── PLAN GENERATOR ──────────────────────────────────────────────────────────

def generate_plan(race_date, distance, ftp, run_pace_ms, weight_kg, prefix="RACE"):
    """
    Generate a list of (workout_dict, date_str) tuples.
    race_date: date object
    distance: key from PROFILES
    ftp: int watts
    run_pace_ms: float m/s (target race pace)
    prefix: short prefix for workout names
    """
    profile = PROFILES[distance]
    weeks   = profile["weeks"]
    race_pct = profile["race_pace_pct"]

    # Power zones
    z1_lo, z1_hi = round(ftp * 0.40), round(ftp * 0.55)
    z2_lo, z2_hi = round(ftp * 0.60), round(ftp * 0.72)
    z3_lo, z3_hi = round(ftp * 0.76), round(ftp * 0.87)
    z4_lo, z4_hi = round(ftp * 0.88), round(ftp * 0.97)
    z5_lo, z5_hi = round(ftp * 1.02), round(ftp * 1.12)
    race_lo = round(ftp * (race_pct - 0.03))
    race_hi = round(ftp * (race_pct + 0.03))

    # Pace targets (m/s)
    easy_ms  = run_pace_ms * 0.85   # easy Z1
    z2_ms    = run_pace_ms * 0.93   # Z2 endurance
    tempo_ms = run_pace_ms * 1.03   # faster than race
    race_ms  = run_pace_ms          # race pace

    workouts = []  # (wkt_dict, date_str)

    # Build week-by-week plan, counting back from race_date
    # Week 1 = furthest from race, last week = race week
    plan_start = race_date - timedelta(weeks=weeks)

    for wk in range(1, weeks + 1):
        wk_start = plan_start + timedelta(weeks=wk - 1)
        remaining = weeks - wk  # weeks left after this one
        is_race_week = (wk == weeks)
        is_taper = (remaining <= 2)
        is_peak  = (weeks // 2 <= wk <= weeks - 3)

        # Volume factor: build up, then taper
        if is_taper:
            vol = 0.6 + remaining * 0.1
        elif is_peak:
            vol = 1.0
        else:
            vol = 0.6 + (wk / weeks) * 0.4
        vol = min(vol, 1.0)

        def d(offset): return (wk_start + timedelta(days=offset)).strftime("%Y-%m-%d")

        # ── BIKE WORKOUTS ──────────────────────────────────────────
        if not is_race_week:
            if is_taper:
                # Short easy spin
                bike_mins = int(45 * vol)
                steps = [
                    _bike_step(1, 1, "warmup",   10, _no_target()),
                    _bike_step(2, 3, "interval", bike_mins, _power_target(z2_lo, z2_hi), float(z2_lo), float(z2_hi)),
                    _bike_step(3, 2, "cooldown",  5, _no_target()),
                ]
                name = f"{prefix}-T{wk} Taper Spin {bike_mins}min"
            elif wk % 3 == 0:
                # Threshold intervals
                steps = [
                    _bike_step(1, 1, "warmup",   15, _no_target()),
                    _bike_step(2, 3, "interval", 20, _power_target(z4_lo, z4_hi), float(z4_lo), float(z4_hi)),
                    _bike_step(3, 4, "recovery",  5, _power_target(z1_lo, z1_hi), float(z1_lo), float(z1_hi)),
                    _bike_step(4, 3, "interval", 20, _power_target(z4_lo, z4_hi), float(z4_lo), float(z4_hi)),
                    _bike_step(5, 4, "recovery",  5, _power_target(z1_lo, z1_hi), float(z1_lo), float(z1_hi)),
                    _bike_step(6, 3, "interval", 15, _power_target(z4_lo, z4_hi), float(z4_lo), float(z4_hi)),
                    _bike_step(7, 2, "cooldown",  10, _no_target()),
                ]
                name = f"{prefix}-T{wk} Threshold 3x20min @{z4_lo}-{z4_hi}W"
            elif wk % 3 == 1:
                # Race sim / long endurance
                bike_mins = int(90 * vol)
                steps = [
                    _bike_step(1, 1, "warmup",   15, _no_target()),
                    _bike_step(2, 3, "interval", bike_mins, _power_target(race_lo, race_hi), float(race_lo), float(race_hi)),
                    _bike_step(3, 2, "cooldown",  10, _no_target()),
                ]
                name = f"{prefix}-T{wk} Race Sim {bike_mins}min @{race_lo}-{race_hi}W"
            else:
                # Z2 endurance
                bike_mins = int(60 * vol)
                steps = [
                    _bike_step(1, 1, "warmup",   10, _no_target()),
                    _bike_step(2, 3, "interval", bike_mins, _power_target(z2_lo, z2_hi), float(z2_lo), float(z2_hi)),
                    _bike_step(3, 2, "cooldown",  5, _no_target()),
                ]
                name = f"{prefix}-T{wk} Z2 Endurance {bike_mins}min @{z2_lo}-{z2_hi}W"

            wkt = {
                "sportType": sport("bike"),
                "workoutName": name,
                "description": f"FTP={ftp}W | Triathlon plan T{wk}/{weeks}",
                "workoutSegments": [{"segmentOrder": 1, "sportType": sport("bike"), "workoutSteps": steps}],
                "estimatedDurationInSecs": sum(s["endConditionValue"] for s in steps),
                "estimatedDistanceInMeters": None,
                "avgTrainingSpeed": None,
                "workoutProvider": None,
                "workoutSourceId": None,
                "isAtp": False,
            }
            workouts.append((wkt, d(1)))  # Tuesday

        elif is_race_week:
            # Pre-race activation ride
            steps = [
                _bike_step(1, 1, "warmup",   5, _no_target()),
                _bike_step(2, 3, "interval", 15, _power_target(z2_lo, z2_hi), float(z2_lo), float(z2_hi)),
                _bike_step(3, 2, "cooldown",  5, _no_target()),
            ]
            name = f"{prefix}-T{wk} Pre-Race Check 20min"
            wkt = {
                "sportType": sport("bike"),
                "workoutName": name,
                "description": f"FTP={ftp}W | Pre-race activation",
                "workoutSegments": [{"segmentOrder": 1, "sportType": sport("bike"), "workoutSteps": steps}],
                "estimatedDurationInSecs": 1500,
                "estimatedDistanceInMeters": None,
                "avgTrainingSpeed": None,
                "workoutProvider": None, "workoutSourceId": None, "isAtp": False,
            }
            workouts.append((wkt, d(5)))  # Friday

        # ── RUN WORKOUTS ───────────────────────────────────────────
        run_km_base = min(profile["run_km"] * 0.8, 12) * vol

        if is_race_week:
            # Easy activation + pre-race
            steps = [
                _run_step(1, 1, "warmup",  dist_m=500),
                _run_step(2, 3, "interval", dist_m=3000,
                          target_type=_pace_target(easy_ms*0.95, easy_ms*1.05),
                          v1=easy_ms*0.95, v2=easy_ms*1.05),
                _run_step(3, 2, "cooldown", dist_m=500),
            ]
            wkt = {
                "sportType": sport("run"),
                "workoutName": f"{prefix}-T{wk} Pre-Race Activation 4km",
                "description": f"Easy pre-race run | pace {ms_to_pace(easy_ms)}/km",
                "workoutSegments": [{"segmentOrder": 1, "sportType": sport("run"), "workoutSteps": steps}],
                "estimatedDurationInSecs": int(4000 / easy_ms),
                "estimatedDistanceInMeters": 4000,
                "avgTrainingSpeed": easy_ms,
                "workoutProvider": None, "workoutSourceId": None, "isAtp": False,
            }
            workouts.append((wkt, d(5)))
        elif is_taper:
            dist = int(run_km_base * 1000)
            steps = [
                _run_step(1, 1, "warmup",  dist_m=500),
                _run_step(2, 3, "interval", dist_m=dist,
                          target_type=_pace_target(z2_ms*0.97, z2_ms*1.03),
                          v1=z2_ms*0.97, v2=z2_ms*1.03),
                _run_step(3, 2, "cooldown", dist_m=500),
            ]
            wkt = {
                "sportType": sport("run"),
                "workoutName": f"{prefix}-T{wk} Taper Run {int(run_km_base)}km @{ms_to_pace(z2_ms)}/km",
                "description": f"Taper run pace {ms_to_pace(z2_ms)}/km",
                "workoutSegments": [{"segmentOrder": 1, "sportType": sport("run"), "workoutSteps": steps}],
                "estimatedDurationInSecs": int((dist+1000) / z2_ms),
                "estimatedDistanceInMeters": dist + 1000,
                "avgTrainingSpeed": z2_ms,
                "workoutProvider": None, "workoutSourceId": None, "isAtp": False,
            }
            workouts.append((wkt, d(3)))
        elif wk % 4 == 0:
            # Long run
            long_km = min(profile["run_km"] * 0.9, 18) * vol
            dist = int(long_km * 1000)
            steps = [
                _run_step(1, 1, "warmup",  dist_m=500),
                _run_step(2, 3, "interval", dist_m=dist,
                          target_type=_pace_target(z2_ms*0.96, z2_ms*1.04),
                          v1=z2_ms*0.96, v2=z2_ms*1.04),
                _run_step(3, 2, "cooldown", dist_m=500),
            ]
            wkt = {
                "sportType": sport("run"),
                "workoutName": f"{prefix}-T{wk} Long Run {int(long_km)}km @{ms_to_pace(z2_ms)}/km",
                "description": f"Long easy run | Z2 pace {ms_to_pace(z2_ms)}/km",
                "workoutSegments": [{"segmentOrder": 1, "sportType": sport("run"), "workoutSteps": steps}],
                "estimatedDurationInSecs": int((dist+1000) / z2_ms),
                "estimatedDistanceInMeters": dist + 1000,
                "avgTrainingSpeed": z2_ms,
                "workoutProvider": None, "workoutSourceId": None, "isAtp": False,
            }
            workouts.append((wkt, d(0)))  # Monday
        else:
            # Tempo / intervals
            tempo_km = min(10, run_km_base) * vol
            dist = int(tempo_km * 1000)
            steps = [
                _run_step(1, 1, "warmup",  dist_m=1000),
                _run_step(2, 3, "interval", dist_m=dist,
                          target_type=_pace_target(race_ms*0.98, race_ms*1.02),
                          v1=race_ms*0.98, v2=race_ms*1.02),
                _run_step(3, 2, "cooldown", dist_m=1000),
            ]
            wkt = {
                "sportType": sport("run"),
                "workoutName": f"{prefix}-T{wk} Tempo {int(tempo_km)}km @{ms_to_pace(race_ms)}/km",
                "description": f"Tempo at race pace {ms_to_pace(race_ms)}/km",
                "workoutSegments": [{"segmentOrder": 1, "sportType": sport("run"), "workoutSteps": steps}],
                "estimatedDurationInSecs": int((dist+2000) / tempo_ms),
                "estimatedDistanceInMeters": dist + 2000,
                "avgTrainingSpeed": tempo_ms,
                "workoutProvider": None, "workoutSourceId": None, "isAtp": False,
            }
            workouts.append((wkt, d(2)))  # Wednesday

        # ── SWIM WORKOUTS ──────────────────────────────────────────
        swim_dist = int(profile["swim_m"] * 0.6 * vol)
        swim_dist = max(200, round(swim_dist / 100) * 100)

        if is_race_week:
            steps = [
                _swim_step(1, 1, "warmup",   200),
                _swim_step(2, 3, "interval", 400),
                _swim_step(3, 2, "cooldown", 100),
            ]
            name = f"{prefix}-T{wk} Pre-Race Swim 700m"
            workouts.append(({
                "sportType": sport("swim"),
                "workoutName": name,
                "description": "Easy pre-race swim",
                "workoutSegments": [{"segmentOrder": 1, "sportType": sport("swim"), "workoutSteps": steps}],
                "estimatedDurationInSecs": 1200,
                "estimatedDistanceInMeters": 700,
                "avgTrainingSpeed": None,
                "workoutProvider": None, "workoutSourceId": None, "isAtp": False,
            }, d(5)))
        else:
            steps = [
                _swim_step(1, 1, "warmup",   min(400, swim_dist // 4)),
                _swim_step(2, 3, "interval", max(200, swim_dist - swim_dist // 4 - 100)),
                _swim_step(3, 2, "cooldown", 100),
            ]
            name = f"{prefix}-T{wk} Swim {swim_dist}m"
            workouts.append(({
                "sportType": sport("swim"),
                "workoutName": name,
                "description": f"Swim training {swim_dist}m",
                "workoutSegments": [{"segmentOrder": 1, "sportType": sport("swim"), "workoutSteps": steps}],
                "estimatedDurationInSecs": int(swim_dist / 1.4),
                "estimatedDistanceInMeters": swim_dist,
                "avgTrainingSpeed": None,
                "workoutProvider": None, "workoutSourceId": None, "isAtp": False,
            }, d(4)))  # Thursday

    return workouts

# ─── GARMIN UPLOAD ───────────────────────────────────────────────────────────

def clean_all(client, prefix):
    """Delete all workouts with matching prefix from library + calendar."""
    http = _get_http(client)
    print(f"Cleaning calendar entries for prefix '{prefix}'...")

    # Clean calendar: 12 months
    today = date.today()
    removed_schedule = 0
    for delta_m in range(0, 13):
        y = today.year + (today.month + delta_m - 1) // 12
        m = (today.month + delta_m - 1) % 12
        try:
            data = client.connectapi(f"/calendar-service/year/{y}/month/{m}")
            for item in data.get("calendarItems", []):
                if item.get("itemType") != "workout": continue
                if not item.get("title", "").startswith(prefix): continue
                sid = item.get("id") or item.get("scheduleId")
                if sid:
                    try:
                        http.request("DELETE", "connectapi",
                            f"/workout-service/schedule/{sid}", api=True)
                        removed_schedule += 1
                        time.sleep(0.1)
                    except: pass
        except: pass
    print(f"  Removed {removed_schedule} calendar entries")

    print(f"Cleaning library for prefix '{prefix}'...")
    workouts = client.get_workouts(start=0, limit=500)
    to_del = [w for w in workouts if w.get("workoutName", "").startswith(prefix)]
    removed_lib = 0
    for w in to_del:
        try:
            http.request("DELETE", "connectapi",
                f"/workout-service/workout/{w['workoutId']}", api=True)
            removed_lib += 1
            time.sleep(0.1)
        except: pass
    print(f"  Removed {removed_lib} library workouts\n")

def upload_all(client, workouts, dry_run=False):
    """Upload workouts and schedule them."""
    print(f"Uploading {len(workouts)} workouts{'(DRY RUN)' if dry_run else ''}...")
    ok = fail = 0
    for wkt, date_str in sorted(workouts, key=lambda x: x[1]):
        name = wkt["workoutName"]
        if dry_run:
            print(f"  [DRY] {date_str}  {name}")
            ok += 1
            continue
        try:
            result = client.save_workout(wkt)
            wid = result.get("workoutId")
            client.schedule_workout(wid, date_str)
            print(f"  ✓ {date_str}  {name}")
            ok += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ {date_str}  {name}: {e}")
            fail += 1
    print(f"\n{'DRY RUN: ' if dry_run else ''}Uploaded: {ok}" +
          (f" | Errors: {fail}" if fail else "") + "\n")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def parse_date(s):
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try: return date.fromisoformat(s) if fmt == "%Y-%m-%d" else \
             date(int(s.split(fmt[-2])[2]), int(s.split(fmt[-2])[1]), int(s.split(fmt[-2])[0]))
        except: pass
    raise ValueError(f"Cannot parse date: {s}")

def main():
    p = argparse.ArgumentParser(description="Triathlon Training Plan Generator for Garmin Connect")
    p.add_argument("--race-date",  help="Race date YYYY-MM-DD (e.g. 2026-09-15)")
    p.add_argument("--distance",   choices=list(PROFILES.keys()), help="Race distance")
    p.add_argument("--ftp",        type=int, help="FTP in watts (from MyWhoosh or Garmin)")
    p.add_argument("--run-pace",   help="Target race pace MM:SS per km (e.g. 5:20)")
    p.add_argument("--weight",     type=float, default=75, help="Body weight in kg")
    p.add_argument("--prefix",     default=None, help="Workout name prefix (default: race name)")
    p.add_argument("--dry-run",    action="store_true", help="Preview without uploading")
    p.add_argument("--reset",      action="store_true", help="Full reset before uploading")
    args = p.parse_args()

    print("\n" + "="*60)
    print("  Triathlon Training Plan Generator")
    print("  Garmin Connect Upload Tool")
    print("="*60 + "\n")

    # Interactive prompts for missing args
    if not args.race_date:
        args.race_date = input("Race date (YYYY-MM-DD): ").strip()
    if not args.distance:
        print("Distance options:", ", ".join(PROFILES.keys()))
        args.distance = input("Distance (70.3 / full / olympic / sprint): ").strip()
    if not args.ftp:
        args.ftp = int(input("FTP in watts (from MyWhoosh or 20min test): ").strip())
    if not args.run_pace:
        args.run_pace = input("Target race run pace MM:SS/km (e.g. 5:20): ").strip()
    if not args.prefix:
        args.prefix = input("Workout name prefix (e.g. RACE or WARSAW): ").strip().upper()

    race_date  = date.fromisoformat(args.race_date)
    distance   = args.distance
    ftp        = args.ftp
    run_pace_ms = pace_to_ms(args.run_pace)
    prefix     = args.prefix
    profile    = PROFILES[distance]

    print(f"\n{'='*60}")
    print(f"  Race:      {profile['label']}")
    print(f"  Date:      {race_date}")
    print(f"  FTP:       {ftp}W")
    print(f"  Run pace:  {args.run_pace}/km ({run_pace_ms:.2f} m/s)")
    print(f"  Weeks:     {profile['weeks']}")
    print(f"  Prefix:    {prefix}")
    print(f"{'='*60}\n")

    # Generate plan
    workouts = generate_plan(race_date, distance, ftp, run_pace_ms, args.weight, prefix)
    print(f"Generated {len(workouts)} workouts\n")

    # Show schedule preview
    by_date = defaultdict(list)
    for wkt, d in workouts:
        by_date[d].append(wkt["workoutName"])
    if len(by_date) > 0:
        first_dates = sorted(by_date)[:5]
        print("First workouts:")
        for d in first_dates:
            for name in by_date[d]:
                print(f"  {d}  {name}")
        print("  ...")

    if args.dry_run:
        print("\nDRY RUN mode — not uploading to Garmin.\n")
        upload_all(None, workouts, dry_run=True)
        return

    # Login
    print("\nLogging in to Garmin Connect...")
    client = login()

    if args.reset:
        print(f"FULL RESET: removing all workouts with prefix '{prefix}'...")
        clean_all(client, prefix)

    upload_all(client, workouts)
    print(f"✓ Done! View your plan at: https://connect.garmin.com/app/calendar\n")

if __name__ == "__main__":
    main()
