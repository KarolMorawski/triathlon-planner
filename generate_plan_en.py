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
import json
import os
import sys
import time
import math
import getpass
from datetime import date, timedelta
from collections import defaultdict

# ─── GARMIN CONNECTION ───────────────────────────────────────────────────────

TOKEN_FILE = os.path.expanduser("~/.garmin_token")
STATE_DIR  = os.path.expanduser("~/.triathlon_plans")

def login():
    try:
        from garminconnect import Garmin
    except ImportError:
        print("ERROR: garminconnect not installed.")
        print("Run: pip install garminconnect")
        sys.exit(1)

    # Try cached OAuth token first (valid for weeks/months, no SSO hit)
    if os.path.isfile(TOKEN_FILE):
        try:
            client = Garmin()
            with open(TOKEN_FILE) as f:
                client.login(tokenstore=f.read())
            print("✓ Logged in to Garmin Connect (cached token)\n")
            return client
        except Exception:
            print("  Cached token expired or invalid — fresh login required.")

    # Fresh login — saves token for future runs
    email    = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")
    client   = Garmin(email=email, password=password, return_on_mfa=True)
    result, state = client.login()
    if result == "needs_mfa":
        client.resume_login(state, input("MFA/2FA code: ").strip())

    # Save OAuth token with owner-only permissions (avoids token leak on shared systems)
    with open(TOKEN_FILE, "w") as f:
        f.write(client.client.dumps())
    os.chmod(TOKEN_FILE, 0o600)
    print(f"✓ Logged in to Garmin Connect (token saved to {TOKEN_FILE})\n")
    return client

def _get_http(client):
    return client.client


def get_garmin_ftp(client):
    """Fetch latest FTP from Garmin Connect user profile. Returns None on failure."""
    try:
        data = client.connectapi("/userprofile-service/userprofile/cycle-power-metrics")
        ftp = data.get("functionalThresholdPower") or data.get("ftp")
        if ftp and int(ftp) > 0:
            return int(ftp)
    except Exception:
        pass
    return None

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

# ─── STEP CONVENIENCE WRAPPERS ───────────────────────────────────────────────

def _bwu(o, mins):   return _bike_step(o, 1, "warmup",   mins, _no_target())
def _bcd(o, mins):   return _bike_step(o, 2, "cooldown", mins, _no_target())
def _bint(o, mins, lo, hi): return _bike_step(o, 3, "interval", mins, _power_target(lo, hi), float(lo), float(hi))
def _brec(o, mins, lo, hi): return _bike_step(o, 4, "recovery", mins, _power_target(lo, hi), float(lo), float(hi))

def _rwu(o, dist_m): return _run_step(o, 1, "warmup",   dist_m=dist_m)
def _rcd(o, dist_m): return _run_step(o, 2, "cooldown", dist_m=dist_m)
def _rint(o, dist_m, lo, hi):
    return _run_step(o, 3, "interval", dist_m=dist_m,
                    target_type=_pace_target(lo, hi), v1=lo, v2=hi)

def _swu(o, dist_m): return _swim_step(o, 1, "warmup",   dist_m)
def _scd(o, dist_m): return _swim_step(o, 2, "cooldown", dist_m)
def _sint(o, dist_m): return _swim_step(o, 3, "interval", dist_m)

def _srest(o, secs):
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": o,
        "stepType": {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5},
        "childStepId": None,
        "description": None,
        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time",
                         "displayOrder": 2, "displayable": True},
        "endConditionValue": float(secs),
        "targetType": _no_target(),
        "targetValueOne": None, "targetValueTwo": None, "targetValueUnit": None,
        "zoneNumber": None,
        "secondaryTargetType": None, "secondaryTargetValueOne": None,
        "secondaryTargetValueTwo": None, "secondaryTargetValueUnit": None,
        "secondaryZoneNumber": None,
        "strokeType": {"strokeTypeId": 0, "strokeTypeKey": None, "displayOrder": 0},
        "equipmentType": {"equipmentTypeId": 0, "equipmentTypeKey": None, "displayOrder": 0},
    }

def _swim_set(start_order, total_dist, interval_dist, rest_secs):
    """Generate alternating interval+rest steps for the main swim set.
    Returns (steps_list, next_free_order, n_intervals, each_dist)."""
    interval_dist = min(interval_dist, total_dist)
    n = max(1, round(total_dist / interval_dist))
    each = total_dist // n
    steps, o = [], start_order
    for i in range(n):
        steps.append(_sint(o, each)); o += 1
        if i < n - 1:
            steps.append(_srest(o, rest_secs)); o += 1
    return steps, o, n, each

def _wkt(sport_key, name, desc, steps, dist_m=None, dur_s=None):
    sp = sport(sport_key)
    return {
        "sportType": sp,
        "workoutName": name,
        "description": desc,
        "workoutSegments": [{"segmentOrder": 1, "sportType": sp, "workoutSteps": steps}],
        "estimatedDurationInSecs": dur_s or int(sum(
            s["endConditionValue"] for s in steps
            if s["endCondition"]["conditionTypeKey"] == "time"
        )) or None,
        "estimatedDistanceInMeters": dist_m,
        "avgTrainingSpeed": None,
        "workoutProvider": None,
        "workoutSourceId": None,
        "isAtp": False,
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

# ─── TARGET TIME / SPLIT CALCULATOR ──────────────────────────────────────────

SPLIT_RATIOS = {
    "sprint":  {"t1t2_min":  5, "swim_pct": 0.13, "bike_pct": 0.47, "run_pct": 0.40},
    "olympic": {"t1t2_min":  7, "swim_pct": 0.12, "bike_pct": 0.52, "run_pct": 0.36},
    "70.3":    {"t1t2_min": 10, "swim_pct": 0.11, "bike_pct": 0.53, "run_pct": 0.36},
    "full":    {"t1t2_min": 12, "swim_pct": 0.11, "bike_pct": 0.52, "run_pct": 0.37},
}

def _parse_hms(s):
    """Parse 'H:MM:SS', 'H:MM' → total minutes (float)."""
    parts = s.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    raise ValueError(f"Cannot parse time: {s!r} — use H:MM:SS or H:MM")

def _fmt_hm(minutes):
    h, m = int(minutes // 60), int(round(minutes % 60))
    return f"{h}:{m:02d}"

def calc_splits(distance, target_time_str, ftp, weight_kg=75, cda=0.32):
    """
    Back-calculate split targets from a finish time goal.
    Physics model (flat course, triathlon position):
      P = (0.5 × rho × CdA × v³  +  Crr × m × g × v) / eta
    Returns dict with split times, paces, watts and run_pace_ms.
    """
    if ftp <= 0:
        raise ValueError(f"FTP must be > 0 (got {ftp})")
    prof   = PROFILES[distance]
    ratios = SPLIT_RATIOS[distance]
    if prof["swim_m"] <= 0:
        raise ValueError(f"Swim distance must be > 0 (got {prof['swim_m']})")

    total_min = _parse_hms(target_time_str)
    t1t2      = ratios["t1t2_min"]
    active    = total_min - t1t2
    if active <= 0:
        raise ValueError(f"Target time {target_time_str} too short for {distance} (must exceed {t1t2} min T1+T2)")
    swim_min  = active * ratios["swim_pct"]
    bike_min  = active * ratios["bike_pct"]
    run_min   = active * ratios["run_pct"]

    run_pace_ms = (prof["run_km"] * 1000) / (run_min * 60)

    v     = (prof["bike_km"] * 1000) / (bike_min * 60)
    watts = (0.5 * 1.225 * cda * v**3 + 0.004 * weight_kg * 9.81 * v) / 0.975

    s100      = (swim_min * 60) / (prof["swim_m"] / 100)
    swim_pace = f"{int(s100 // 60)}:{int(s100 % 60):02d}/100m"

    return {
        "total_min":    total_min,
        "t1t2_min":     t1t2,
        "swim_min":     swim_min,
        "bike_min":     bike_min,
        "run_min":      run_min,
        "swim_pace":    swim_pace,
        "bike_kmh":     round(v * 3.6, 1),
        "bike_watts":   round(watts),
        "bike_pct_ftp": watts / ftp,
        "run_pace_ms":  run_pace_ms,
        "run_pace_str": ms_to_pace(run_pace_ms),
    }

# ─── PLAN GENERATOR ──────────────────────────────────────────────────────────

def generate_plan(race_date, distance, ftp, run_pace_ms, weight_kg, prefix="RACE",
                  race_bike_pct=None, vol_scale=1.0):
    """
    Generate a list of (workout_dict, date_str) tuples.

    race_bike_pct: override bike race zone center (% FTP); None = use profile default.
                   Derived automatically when --target-time is provided.

    Weekly structure by phase:
      Base  (first ~1/3): 2/sport = 6 sessions/week
        Mon Swim-Tech, Tue Bike-Quality, Wed Run-Tempo,
        Thu Swim-Endurance + Bike-Z2, Sun Run-Long
      Build (middle):     3/sport = 9 sessions/week
        + Fri Swim-RaceSim + Run-Easy, Sat Bike-Long
      Taper (last 2 weeks): 2/sport = 6 sessions/week (short)
        Tue Bike-Z3, Wed Run-Easy, Thu Swim, Fri Swim+Bike-Spin, Sun Run-Easy
      Race week: 3 pre-race activation sessions on Friday
    """
    if ftp <= 0:
        raise ValueError(f"FTP must be > 0 (got {ftp})")
    profile  = PROFILES[distance]
    weeks    = profile["weeks"]
    rp       = race_bike_pct if race_bike_pct is not None else profile["race_pace_pct"]
    # Cap race power at sustainable level — sub-1 hour TT power, never above FTP
    if rp > 0.95:
        print(f"⚠ Race bike power {rp:.0%} FTP exceeds sustainable threshold — capping at 95% FTP")
        rp = 0.95

    # Power zones
    z = lambda lo, hi: (round(ftp * lo), round(ftp * hi))
    Z1 = z(0.40, 0.55); Z2 = z(0.60, 0.72); Z3 = z(0.76, 0.87)
    Z4 = z(0.88, 0.97); Z5 = z(1.02, 1.12)
    ZR = z(rp - 0.03, rp + 0.03)

    # Run paces (m/s)
    easy   = run_pace_ms * 0.85
    z2_run = run_pace_ms * 0.93
    race_p = run_pace_ms

    taper_start_wk = weeks - 2
    plan_start     = race_date - timedelta(weeks=weeks)
    workouts       = []

    for wk in range(1, weeks + 1):
        wk_start  = plan_start + timedelta(weeks=wk - 1)
        remaining = weeks - wk

        is_race  = (wk == weeks)
        is_taper = not is_race and (wk >= taper_start_wk)
        is_build = not is_race and not is_taper and (wk > weeks // 3)

        if is_taper:
            vol = max(0.5, 0.6 + remaining * 0.1)
        elif is_race:
            vol = 0.3
        else:
            vol = min(1.0, 0.6 + (wk / taper_start_wk) * 0.4)
        vol *= vol_scale

        def D(offset, _ws=wk_start):
            return (_ws + timedelta(days=offset)).strftime("%Y-%m-%d")
        tag = f"{prefix}-T{wk:02d}"

        # ─────────────────────────── RACE WEEK ───────────────────────────────
        if is_race:
            workouts.append((_wkt("bike", f"{tag} Pre-Race Check 20min",
                f"FTP={ftp}W | pre-race activation",
                [_bwu(1,5), _bint(2,15,*Z2), _bcd(3,5)]), D(4)))
            workouts.append((_wkt("run", f"{tag} Pre-Race Activation 4km",
                f"Easy pre-race | {ms_to_pace(easy)}/km",
                [_rwu(1,500), _rint(2,3000,easy*0.95,easy*1.05), _rcd(3,500)], 4000), D(4)))
            workouts.append((_wkt("swim", f"{tag} Pre-Race Swim 700m",
                "Easy pre-race swim",
                [_swu(1,200), _sint(2,400), _scd(3,100)], 700), D(4)))
            continue

        # ─────────────────────────── TAPER ───────────────────────────────────
        if is_taper:
            m = max(30, int(45 * vol))
            workouts.append((_wkt("bike", f"{tag} Taper Z3 {m}min @{Z3[0]}-{Z3[1]}W",
                f"FTP={ftp}W | taper activation",
                [_bwu(1,10), _bint(2,m,*Z3), _bcd(3,5)]), D(1)))
            m2 = max(20, int(30 * vol))
            workouts.append((_wkt("bike", f"{tag} Taper Spin {m2}min @{Z2[0]}-{Z2[1]}W",
                f"FTP={ftp}W | taper spin",
                [_bwu(1,10), _bint(2,m2,*Z2), _bcd(3,5)]), D(4)))

            km = max(5, int(8 * vol))
            workouts.append((_wkt("run", f"{tag} Taper Run {km}km @{ms_to_pace(z2_run)}/km",
                "Taper easy run",
                [_rwu(1,500), _rint(2,km*1000,z2_run*0.97,z2_run*1.03), _rcd(3,500)],
                (km+1)*1000), D(2)))
            km2 = max(4, int(6 * vol))
            workouts.append((_wkt("run", f"{tag} Taper Easy {km2}km @{ms_to_pace(easy)}/km",
                "Taper recovery run",
                [_rwu(1,500), _rint(2,km2*1000,easy*0.97,easy*1.03), _rcd(3,500)],
                (km2+1)*1000), D(6)))

            dist_a = max(800, round(int(profile["swim_m"] * 0.4 * vol) / 100) * 100)
            wu_d = min(300, dist_a // 4); main_d = max(200, dist_a - wu_d - 100)
            workouts.append((_wkt("swim", f"{tag} Taper Swim {dist_a}m",
                f"Taper swim {dist_a}m",
                [_swu(1,wu_d), _sint(2,main_d), _scd(3,100)], dist_a), D(3)))
            dist_b = max(400, round(int(profile["swim_m"] * 0.25 * vol) / 100) * 100)
            wu_d = min(200, dist_b // 4); main_d = max(200, dist_b - wu_d - 100)
            workouts.append((_wkt("swim", f"{tag} Taper Pre-Race Swim {dist_b}m",
                f"Taper swim {dist_b}m",
                [_swu(1,wu_d), _sint(2,main_d), _scd(3,100)], dist_b), D(4)))
            continue

        # ─────────────────────────── BASE + BUILD ────────────────────────────

        swim_base = int(profile["swim_m"] * 0.6 * vol)

        # ── SWIM A — technique (Mon D0) — 100m intervals, 20s rest ──────────────
        dist_a = max(600, round(int(swim_base * 0.55) / 100) * 100)
        wu_d = min(300, dist_a // 4); main_d = max(200, dist_a - wu_d - 100)
        int_steps, next_o, n_int, each_d = _swim_set(2, main_d, 100, 20)
        workouts.append((_wkt("swim", f"{tag} Swim Tech {dist_a}m",
            f"Technique & drills {dist_a}m | {n_int}×{each_d}m + 20s rest",
            [_swu(1,wu_d)] + int_steps + [_scd(next_o,100)], dist_a), D(0)))

        # ── SWIM B — endurance (Thu D3) — 200m intervals, 15s rest ──────────────
        dist_b = max(800, round(int(swim_base * 0.75) / 100) * 100)
        wu_d = min(400, dist_b // 4); main_d = max(300, dist_b - wu_d - 100)
        int_steps, next_o, n_int, each_d = _swim_set(2, main_d, 200, 15)
        workouts.append((_wkt("swim", f"{tag} Swim Endurance {dist_b}m",
            f"Endurance {dist_b}m | {n_int}×{each_d}m + 15s rest",
            [_swu(1,wu_d)] + int_steps + [_scd(next_o,100)], dist_b), D(3)))

        # ── SWIM C — race-sim (Fri D4) — 400m intervals, 10s rest — BUILD only ──
        if is_build:
            dist_c = max(400, round(int(profile["swim_m"] * 0.85 * vol) / 100) * 100)
            wu_d = min(200, dist_c // 5); main_d = max(200, dist_c - wu_d - 100)
            int_steps, next_o, n_int, each_d = _swim_set(2, main_d, 400, 10)
            workouts.append((_wkt("swim", f"{tag} Swim Race-Sim {dist_c}m",
                f"Race-pace {dist_c}m | {n_int}×{each_d}m + 10s rest",
                [_swu(1,wu_d)] + int_steps + [_scd(next_o,100)], dist_c), D(4)))

        # ── BIKE A — main quality session (Tue D1) ────────────────────────────
        q = wk % 3
        if q == 0:
            workouts.append((_wkt("bike", f"{tag} Threshold 3x20min @{Z4[0]}-{Z4[1]}W",
                f"FTP={ftp}W | threshold",
                [_bwu(1,15),
                 _bint(2,20,*Z4), _brec(3,5,*Z1),
                 _bint(4,20,*Z4), _brec(5,5,*Z1),
                 _bint(6,15,*Z4), _bcd(7,10)]), D(1)))
        elif q == 1:
            m = max(45, int(80 * vol))
            workouts.append((_wkt("bike", f"{tag} Race Sim {m}min @{ZR[0]}-{ZR[1]}W",
                f"FTP={ftp}W | race simulation",
                [_bwu(1,15), _bint(2,m,*ZR), _bcd(3,10)]), D(1)))
        else:
            if is_build:
                workouts.append((_wkt("bike", f"{tag} VO2max 4x5min @{Z5[0]}-{Z5[1]}W",
                    f"FTP={ftp}W | VO2max",
                    [_bwu(1,15),
                     _bint(2,5,*Z5), _brec(3,3,*Z1),
                     _bint(4,5,*Z5), _brec(5,3,*Z1),
                     _bint(6,5,*Z5), _brec(7,3,*Z1),
                     _bint(8,5,*Z5), _bcd(9,10)]), D(1)))
            else:
                m = max(40, int(60 * vol))
                workouts.append((_wkt("bike", f"{tag} Tempo {m}min @{Z3[0]}-{Z3[1]}W",
                    f"FTP={ftp}W | tempo Z3",
                    [_bwu(1,10), _bint(2,m,*Z3), _bcd(3,5)]), D(1)))

        # ── BIKE B — Z2 endurance (Thu D3) ───────────────────────────────────
        m = max(45, int(70 * vol))
        workouts.append((_wkt("bike", f"{tag} Z2 Endurance {m}min @{Z2[0]}-{Z2[1]}W",
            f"FTP={ftp}W | aerobic base",
            [_bwu(1,10), _bint(2,m,*Z2), _bcd(3,5)]), D(3)))

        # ── BIKE C — long ride (Sat D5) — BUILD only ─────────────────────────
        if is_build:
            m_long = max(90, int(150 * vol))
            workouts.append((_wkt("bike", f"{tag} Long Ride {m_long}min @{Z2[0]}-{Z2[1]}W",
                f"FTP={ftp}W | long Z2",
                [_bwu(1,15), _bint(2,m_long,*Z2), _bcd(3,10)]), D(5)))

        # ── RUN A — tempo (Wed D2) ────────────────────────────────────────────
        km = min(12, max(6, int(10 * vol)))
        workouts.append((_wkt("run", f"{tag} Tempo {km}km @{ms_to_pace(race_p)}/km",
            f"Race pace run {ms_to_pace(race_p)}/km",
            [_rwu(1,1000), _rint(2,km*1000,race_p*0.98,race_p*1.02), _rcd(3,1000)],
            (km+2)*1000), D(2)))

        # ── RUN B — long run (Sun D6) ─────────────────────────────────────────
        max_long = 18 if distance in ("full", "70.3") else 12
        km_long = min(max_long, max(8, int(profile["run_km"] * 0.85 * vol)))
        workouts.append((_wkt("run", f"{tag} Long Run {km_long}km @{ms_to_pace(z2_run)}/km",
            "Long Z2 run",
            [_rwu(1,500), _rint(2,km_long*1000,z2_run*0.96,z2_run*1.04), _rcd(3,500)],
            (km_long+1)*1000), D(6)))

        # ── RUN C — easy recovery (Fri D4) — BUILD only ──────────────────────
        if is_build:
            km_easy = max(6, int(9 * vol))
            workouts.append((_wkt("run", f"{tag} Easy Run {km_easy}km @{ms_to_pace(easy)}/km",
                "Easy recovery run",
                [_rwu(1,500), _rint(2,km_easy*1000,easy*0.97,easy*1.03), _rcd(3,500)],
                (km_easy+1)*1000), D(4)))

    return workouts

# ─── GARMIN UPLOAD ───────────────────────────────────────────────────────────

def clean_all(client, prefix):
    """Delete all workouts with matching prefix from library + calendar."""
    http = _get_http(client)
    print(f"Cleaning calendar entries for prefix '{prefix}'...")

    # Clean calendar: 12 months
    today = date.today()
    removed_schedule = 0
    for delta_m in range(-1, 14):
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
                    except Exception: pass
        except Exception: pass
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
        except Exception: pass
    print(f"  Removed {removed_lib} library workouts\n")

def upload_all(client, workouts, dry_run=False):
    """Upload workouts and schedule them."""
    print(f"Uploading {len(workouts)} workouts{'(DRY RUN)' if dry_run else ''}...")
    ok = fail = 0
    uploaded = []
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
            uploaded.append({
                "name":       name,
                "workout_id": wid,
                "date":       date_str,
                "sport":      wkt["sportType"]["sportTypeKey"],
            })
            print(f"  ✓ {date_str}  {name}")
            ok += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ {date_str}  {name}: {e}")
            fail += 1
    print(f"\n{'DRY RUN: ' if dry_run else ''}Uploaded: {ok}" +
          (f" | Errors: {fail}" if fail else "") + "\n")
    return ok, fail, uploaded

def save_plan_state(prefix, config, uploaded):
    """Persist uploaded workout IDs so update_plan.py can update future weeks."""
    os.makedirs(STATE_DIR, exist_ok=True)
    state = {
        "version":      1,
        "generated_at": date.today().isoformat(),
        "prefix":       prefix,
        "config":       config,
        "workouts":     uploaded,
    }
    path = os.path.join(STATE_DIR, f"{prefix}.json")
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    print(f"Plan state saved → {path}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Triathlon Training Plan Generator for Garmin Connect")
    p.add_argument("--race-date",    help="Race date YYYY-MM-DD (e.g. 2026-09-15)")
    p.add_argument("--distance",     choices=list(PROFILES.keys()), help="Race distance")
    p.add_argument("--ftp",          type=int, help="FTP in watts (from MyWhoosh or Garmin)")
    p.add_argument("--auto-ftp",     action="store_true",
                   help="Read FTP from Garmin Connect (login required)")
    p.add_argument("--run-pace",     help="Target race pace MM:SS per km (e.g. 5:20)")
    p.add_argument("--target-time",  help="Target finish time H:MM:SS — derives run pace + bike zone")
    p.add_argument("--weight",       type=float, default=75, help="Body weight in kg")
    p.add_argument("--cda",          type=float, default=0.32, help="CdA m² for bike power model (default: 0.32)")
    p.add_argument("--prefix",       default=None, help="Workout name prefix (default: race name)")
    p.add_argument("--vol-scale",    type=float, default=1.0,
                   help="Volume multiplier (default: 1.0). Use strava_suggest.py to calibrate.")
    p.add_argument("--dry-run",      action="store_true", help="Preview without uploading")
    p.add_argument("--reset",        action="store_true", help="Full reset before uploading")
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
    if args.auto_ftp and not args.ftp:
        print("Logging in to Garmin to read FTP...")
        _c = login()
        garmin_ftp = get_garmin_ftp(_c)
        if garmin_ftp:
            args.ftp = garmin_ftp
            print(f"  Auto FTP from Garmin: {garmin_ftp}W\n")
        else:
            print("  ⚠ Could not read FTP from Garmin — enter it manually.")
    if not args.ftp:
        args.ftp = int(input("FTP in watts (from MyWhoosh or 20min test): ").strip())
    if not args.target_time and not args.run_pace:
        print("Enter target finish time OR run pace (one is required):")
        args.target_time = input("  Target finish time H:MM:SS (or Enter to skip): ").strip() or None
        if not args.target_time:
            args.run_pace = input("  Target race run pace MM:SS/km (e.g. 5:20): ").strip()
    if not args.prefix:
        args.prefix = input("Workout name prefix (e.g. RACE or WARSAW): ").strip().upper()

    race_date = date.fromisoformat(args.race_date)
    distance  = args.distance
    ftp       = args.ftp
    prefix    = args.prefix
    profile   = PROFILES[distance]

    # Resolve run pace and bike zone from target time or explicit pace
    race_bike_pct = None
    if args.target_time:
        splits        = calc_splits(distance, args.target_time, ftp, args.weight, args.cda)
        run_pace_ms   = splits["run_pace_ms"]
        race_bike_pct = splits["bike_pct_ftp"]
    else:
        run_pace_ms = pace_to_ms(args.run_pace)

    print(f"\n{'='*60}")
    print(f"  Race:      {profile['label']}")
    print(f"  Date:      {race_date}")
    print(f"  FTP:       {ftp}W  |  Weight: {args.weight}kg")
    print(f"  Weeks:     {profile['weeks']}")
    print(f"  Prefix:    {prefix}")

    if args.target_time:
        s = splits
        pct_str = f"{s['bike_pct_ftp']*100:.0f}% FTP"
        warn = "  ⚠ >100% FTP!" if s['bike_pct_ftp'] > 1.0 else ""
        print(f"\n  Target:    {args.target_time}  →  splits:")
        print(f"    Swim:     {_fmt_hm(s['swim_min'])}  @ {s['swim_pace']}")
        print(f"    T1+T2:    {_fmt_hm(s['t1t2_min'])}")
        print(f"    Bike:     {_fmt_hm(s['bike_min'])}  @ {s['bike_kmh']} km/h  →  ~{s['bike_watts']}W ({pct_str}){warn}")
        print(f"    Run:      {_fmt_hm(s['run_min'])}  @ {s['run_pace_str']}/km")
    else:
        print(f"  Run pace:  {args.run_pace}/km")
    print(f"{'='*60}\n")

    # Generate plan
    if args.vol_scale != 1.0:
        print(f"Volume scale: {args.vol_scale}× (use strava_suggest.py to recalibrate)\n")
    workouts = generate_plan(race_date, distance, ftp, run_pace_ms, args.weight, prefix,
                             race_bike_pct=race_bike_pct, vol_scale=args.vol_scale)
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

    ok, fail, uploaded = upload_all(client, workouts)
    print(f"✓ Done! View your plan at: https://connect.garmin.com/app/calendar\n")
    plan_config = {
        "race_date":    str(race_date),
        "distance":     distance,
        "ftp":          ftp,
        "weight_kg":    args.weight,
        "cda":          args.cda,
        "vol_scale":    args.vol_scale,
        "run_pace_ms":  run_pace_ms,
        "run_pace_str": ms_to_pace(run_pace_ms),
    }
    if args.target_time:
        plan_config["target_time"]   = args.target_time
        plan_config["race_bike_pct"] = race_bike_pct
    save_plan_state(prefix, plan_config, uploaded)

    # ── MyWhoosh / Zwift .zwo files ───────────────────────────────────────────
    zwo_ans = input("Generate .zwo files for MyWhoosh/Zwift? (yes/no): ").strip().lower()
    if zwo_ans in ("yes", "y"):
        try:
            from mywhoosh_season import generate_for_distance
            out = f"./mywhoosh_{prefix.lower()}"
            generate_for_distance(prefix, distance, ftp, out)
        except ImportError:
            print("  mywhoosh_season.py not found — place it in the same folder.")

if __name__ == "__main__":
    main()
