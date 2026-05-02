#!/usr/bin/env python3
"""
Triathlon Season Plan Generator for Garmin Connect
===================================================
Plan an entire triathlon season with multiple races in one script.
Each race gets its own training block. Full reset before each upload.

Usage:
  python3 season_plan.py                        # interactive mode
  python3 season_plan.py --config season.json   # load from config file
  python3 season_plan.py --dry-run              # preview without uploading
  python3 season_plan.py --reset                # full reset then upload

Config file format (season.json):
  {
    "ftp": 250,
    "run_pace": "5:20",
    "weight_kg": 80,
    "races": [
      {"name": "WARSAW",  "date": "2026-06-07", "distance": "70.3"},
      {"name": "POZNAN",  "date": "2026-08-30", "distance": "70.3"}
    ]
  }
"""

import argparse
import re
import sys
import time
import json
import getpass
import os
from datetime import date, timedelta
from collections import defaultdict

# ─── GARMIN LOGIN ────────────────────────────────────────────────────────────

TOKEN_FILE = os.path.expanduser("~/.garmin_token")

_PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")

def _validate_prefix(p):
    """Reject prefixes that could escape STATE_DIR or contain unsafe characters."""
    if not _PREFIX_RE.match(p):
        sys.exit(f"ERROR: Invalid race name '{p}'. Allowed: A-Z, 0-9, _, - (must start alphanumeric).")
STATE_DIR  = os.path.expanduser("~/.triathlon_plans")

def login():
    try:
        from garminconnect import Garmin
    except ImportError:
        print("ERROR: garminconnect not installed.")
        print("Fix: pip install garminconnect")
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

def _http(client):
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

# ─── RACE PROFILES ───────────────────────────────────────────────────────────

PROFILES = {
    "70.3":    {"label":"Half Ironman 70.3", "weeks":12, "swim_m":1900, "bike_km":90,  "run_km":21.1, "race_bike_pct":0.82},
    "full":    {"label":"Full Ironman",      "weeks":16, "swim_m":3800, "bike_km":180, "run_km":42.2, "race_bike_pct":0.72},
    "olympic": {"label":"Olympic Distance",  "weeks":10, "swim_m":1500, "bike_km":40,  "run_km":10,   "race_bike_pct":0.88},
    "sprint":  {"label":"Sprint Distance",   "weeks":8,  "swim_m":750,  "bike_km":20,  "run_km":5,    "race_bike_pct":0.95},
}


def _validate_config(cfg, source="config"):
    """Validate season config structure. Exits with a clear message on failure."""
    if not isinstance(cfg, dict):
        sys.exit(f"ERROR in {source}: top-level must be a JSON object")
    if "ftp" not in cfg:
        sys.exit(f"ERROR in {source}: missing required field 'ftp'")
    if "races" not in cfg or not isinstance(cfg["races"], list) or not cfg["races"]:
        sys.exit(f"ERROR in {source}: 'races' must be a non-empty list")
    for i, race in enumerate(cfg["races"]):
        if not isinstance(race, dict):
            sys.exit(f"ERROR in {source}: races[{i}] must be an object")
        for field in ("name", "date", "distance"):
            if field not in race:
                sys.exit(f"ERROR in {source}: races[{i}] missing '{field}'")
        if race["distance"] not in PROFILES:
            sys.exit(f"ERROR in {source}: races[{i}].distance='{race['distance']}' "
                     f"not in {list(PROFILES.keys())}")
        try:
            date.fromisoformat(race["date"])
        except (TypeError, ValueError):
            sys.exit(f"ERROR in {source}: races[{i}].date='{race['date']}' "
                     f"is not ISO format YYYY-MM-DD")

# ─── SPORT TYPES ─────────────────────────────────────────────────────────────

def _sport(key):
    return {"run":  {"sportTypeId":1,"sportTypeKey":"running",  "displayOrder":1},
            "bike": {"sportTypeId":2,"sportTypeKey":"cycling",  "displayOrder":2},
            "swim": {"sportTypeId":4,"sportTypeKey":"swimming", "displayOrder":4}}[key]

# ─── TARGET TYPES ────────────────────────────────────────────────────────────
# CONFIRMED via Garmin API inspection:
#   id=1  no.target     → no intensity target (warmup/cooldown)
#   id=2  power.zone    → absolute watts (cycling intervals)
#   id=4  heart.rate.zone → bpm range
#   id=6  pace.zone     → m/s (running)

def _no_tgt():
    return {"workoutTargetTypeId":1,"workoutTargetTypeKey":"no.target","displayOrder":1}
def _pwr_tgt(lo_w, hi_w):
    return {"workoutTargetTypeId":2,"workoutTargetTypeKey":"power.zone","displayOrder":2}
def _pace_tgt(lo_ms, hi_ms):
    return {"workoutTargetTypeId":6,"workoutTargetTypeKey":"pace.zone","displayOrder":6}

# ─── STEP FACTORIES ──────────────────────────────────────────────────────────

def _step(order, type_id, type_key, end_type, end_val, tgt, v1=None, v2=None, extra=None):
    s = {
        "type":"ExecutableStepDTO",
        "stepOrder":order,
        "stepType":{"stepTypeId":type_id,"stepTypeKey":type_key,"displayOrder":type_id},
        "childStepId":None,"description":None,
        "endCondition":{"conditionTypeId":end_type,
                        "conditionTypeKey":("time" if end_type==2 else "distance"),
                        "displayOrder":end_type,"displayable":True},
        "endConditionValue":float(end_val),
        "targetType":tgt,
        "targetValueOne":v1,"targetValueTwo":v2,
        "targetValueUnit":None,"zoneNumber":None,
        "secondaryTargetType":None,"secondaryTargetValueOne":None,
        "secondaryTargetValueTwo":None,"secondaryTargetValueUnit":None,
        "secondaryZoneNumber":None,"endConditionZone":None,
        "strokeType":None,"equipmentType":None,
    }
    if extra:
        s.update(extra)
    return s

def bike_wu(o, mins):
    return _step(o, 1,"warmup",   2, mins*60, _no_tgt())
def bike_cd(o, mins):
    return _step(o, 2,"cooldown", 2, mins*60, _no_tgt())
def bike_int(o, mins, lo_w, hi_w):
    return _step(o, 3,"interval", 2, mins*60, _pwr_tgt(lo_w,hi_w), float(lo_w), float(hi_w))
def bike_rec(o, mins, lo_w, hi_w):
    return _step(o, 4,"recovery", 2, mins*60, _pwr_tgt(lo_w,hi_w), float(lo_w), float(hi_w))

def run_wu(o, dist_m):
    return _step(o, 1,"warmup",   3, dist_m, _no_tgt())
def run_cd(o, dist_m):
    return _step(o, 2,"cooldown", 3, dist_m, _no_tgt())
def run_int(o, dist_m, lo_ms, hi_ms):
    return _step(o, 3,"interval", 3, dist_m, _pace_tgt(lo_ms,hi_ms), lo_ms, hi_ms)

def swim_wu(o, dist_m):
    return _step(o, 1,"warmup",   3, dist_m, _no_tgt(),
                 extra={"strokeType":{"strokeTypeId":0,"strokeTypeKey":None,"displayOrder":0},
                        "equipmentType":{"equipmentTypeId":0,"equipmentTypeKey":None,"displayOrder":0}})
def swim_cd(o, dist_m):
    return _step(o, 2,"cooldown", 3, dist_m, _no_tgt(),
                 extra={"strokeType":{"strokeTypeId":0,"strokeTypeKey":None,"displayOrder":0},
                        "equipmentType":{"equipmentTypeId":0,"equipmentTypeKey":None,"displayOrder":0}})
def swim_int(o, dist_m):
    return _step(o, 3,"interval", 3, dist_m, _no_tgt(),
                 extra={"strokeType":{"strokeTypeId":0,"strokeTypeKey":None,"displayOrder":0},
                        "equipmentType":{"equipmentTypeId":0,"equipmentTypeKey":None,"displayOrder":0}})
def swim_rest(o, secs):
    return _step(o, 5,"rest", 2, secs, _no_tgt(),
                 extra={"strokeType":{"strokeTypeId":0,"strokeTypeKey":None,"displayOrder":0},
                        "equipmentType":{"equipmentTypeId":0,"equipmentTypeKey":None,"displayOrder":0}})
def swim_set(start_order, total_dist, interval_dist, rest_secs):
    interval_dist = min(interval_dist, total_dist)
    n = max(1, round(total_dist / interval_dist))
    each = total_dist // n
    steps, o = [], start_order
    for i in range(n):
        steps.append(swim_int(o, each)); o += 1
        if i < n - 1:
            steps.append(swim_rest(o, rest_secs)); o += 1
    return steps, o, n, each

# ─── WORKOUT BUILDER ─────────────────────────────────────────────────────────

def _wkt(sport_key, name, desc, steps, dist_m=None, dur_s=None):
    sp = _sport(sport_key)
    return {
        "sportType": sp,
        "workoutName": name,
        "description": desc,
        "workoutSegments": [{"segmentOrder":1,"sportType":sp,"workoutSteps":steps}],
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

def ms_to_pace(ms):
    spk = 1000.0/ms; m=int(spk//60); s=int(spk%60)
    return f"{m}:{s:02d}"

def pace_to_ms(s):
    p = s.strip().split(":")
    return 1000.0/(int(p[0])*60+int(p[1]))

# ─── TARGET TIME / SPLIT CALCULATOR ──────────────────────────────────────────

# Default split ratios (pct of active time after T1+T2) — based on age-group data
SPLIT_RATIOS = {
    "sprint":  {"t1t2_min":  5, "swim_pct": 0.13, "bike_pct": 0.47, "run_pct": 0.40},
    "olympic": {"t1t2_min":  7, "swim_pct": 0.12, "bike_pct": 0.52, "run_pct": 0.36},
    "70.3":    {"t1t2_min": 10, "swim_pct": 0.11, "bike_pct": 0.53, "run_pct": 0.36},
    "full":    {"t1t2_min": 12, "swim_pct": 0.11, "bike_pct": 0.52, "run_pct": 0.37},
}

def _parse_hms(s):
    """Parse 'H:MM:SS', 'H:MM', or 'MM:SS' → total minutes (float)."""
    parts = s.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    raise ValueError(f"Cannot parse time: {s!r} — use H:MM:SS or H:MM")

def _fmt_hm(minutes):
    """Format minutes → 'H:MM'."""
    h, m = int(minutes // 60), int(round(minutes % 60))
    return f"{h}:{m:02d}"

def calc_splits(distance, target_time_str, ftp, weight_kg=75, cda=0.32,
                custom_swim_min=None, custom_t1t2_min=None):
    """
    Back-calculate per-sport split targets from a finish time goal.

    Physics model (flat course):
      P = (0.5 × rho × CdA × v³  +  Crr × m × g × v) / eta
      CdA  = 0.32 m²  (triathlon/TT position, override via config 'cda')
      Crr  = 0.004    (triathlon tires on tarmac)
      rho  = 1.225 kg/m³ (sea level, 15°C)
      eta  = 0.975    (drivetrain efficiency)

    Returns dict with all split times, paces, watts and run_pace_ms for
    use in generate_race_block().
    """
    if ftp <= 0:
        raise ValueError(f"FTP must be > 0 (got {ftp})")
    prof   = PROFILES[distance]
    ratios = SPLIT_RATIOS[distance]
    if prof["swim_m"] <= 0:
        raise ValueError(f"Swim distance must be > 0 (got {prof['swim_m']})")

    total_min = _parse_hms(target_time_str)
    t1t2      = float(custom_t1t2_min) if custom_t1t2_min is not None else ratios["t1t2_min"]
    active    = total_min - t1t2
    if active <= 0:
        raise ValueError(f"Target time {target_time_str} too short for {distance} (must exceed {t1t2} min T1+T2)")

    if custom_swim_min is not None:
        swim_min = float(custom_swim_min)
        left     = active - swim_min
        bike_rel = ratios["bike_pct"] / (ratios["bike_pct"] + ratios["run_pct"])
        bike_min = left * bike_rel
        run_min  = left * (1 - bike_rel)
    else:
        swim_min = active * ratios["swim_pct"]
        bike_min = active * ratios["bike_pct"]
        run_min  = active * ratios["run_pct"]

    # Run pace
    run_pace_ms = (prof["run_km"] * 1000) / (run_min * 60)

    # Bike power — simplified road physics
    v     = (prof["bike_km"] * 1000) / (bike_min * 60)   # m/s
    watts = (0.5 * 1.225 * cda * v**3 + 0.004 * weight_kg * 9.81 * v) / 0.975
    pct   = watts / ftp

    # Swim pace
    s100  = (swim_min * 60) / (prof["swim_m"] / 100)
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
        "bike_pct_ftp": pct,
        "run_pace_ms":  run_pace_ms,
        "run_pace_str": ms_to_pace(run_pace_ms),
    }

# ─── PLAN GENERATOR ──────────────────────────────────────────────────────────

def generate_race_block(race_date, distance, ftp, run_pace_ms, prefix,
                        race_bike_pct=None, vol_scale=1.0, override_weeks=None):
    """
    Returns list of (workout_dict, date_str) for one race block.
    Counts back `weeks` from race_date.
    Full reset friendly: all names start with prefix.

    race_bike_pct: override for bike race zone center (% FTP).
                   If None, uses the profile default (e.g. 0.72 for full).
                   Derived automatically when target_time is provided.

    Weekly structure by phase:
      Base  (first ~1/3 of weeks): 2/sport = 6 sessions/week
        Mon Swim-Tech, Tue Bike-Quality, Wed Run-Tempo,
        Thu Swim-Endurance, Sat Bike-Z2, Sun Run-Long
      Build (middle weeks):        3/sport = 9 sessions/week
        + Thu Bike-Z2, Fri Swim-RaceSim + Run-Easy, Sat Bike-Long, Sun Run-Long
      Taper (last 2 training weeks): 2/sport = 6 sessions/week (short)
        Tue Bike-Z3, Wed Run-Easy, Thu Swim, Fri Swim+Bike-Spin, Sun Run-Easy
      Race week: 3 pre-race activation sessions on Fri
    """
    if ftp <= 0:
        raise ValueError(f"FTP must be > 0 (got {ftp})")
    prof  = PROFILES[distance]
    weeks = override_weeks if override_weeks is not None else prof["weeks"]
    rp    = race_bike_pct if race_bike_pct is not None else prof["race_bike_pct"]
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

    taper_start_wk = weeks - 2   # first taper week (e.g. 14 for 16-week plan)
    plan_start = race_date - timedelta(weeks=weeks)
    workouts   = []

    for wk in range(1, weeks + 1):
        wk_start  = plan_start + timedelta(weeks=wk - 1)
        remaining = weeks - wk

        is_race  = (wk == weeks)
        is_taper = not is_race and (wk >= taper_start_wk)
        is_build = not is_race and not is_taper and (wk > weeks // 3)
        # is_base  = not is_race and not is_taper and not is_build

        if is_taper:
            vol = max(0.5, 0.6 + remaining * 0.1)
        elif is_race:
            vol = 0.3
        else:
            vol = min(1.0, 0.6 + (wk / taper_start_wk) * 0.4)
        vol *= vol_scale

        def D(offset, _ws=wk_start): return (_ws + timedelta(days=offset)).strftime("%Y-%m-%d")
        tag = f"{prefix}-T{wk:02d}"

        # ─────────────────────────── RACE WEEK ───────────────────────────────
        if is_race:
            steps = [bike_wu(1, 5), bike_int(2, 15, *Z2), bike_cd(3, 5)]
            workouts.append((_wkt("bike", f"{tag} Pre-Race Check 20min",
                f"FTP={ftp}W | pre-race activation", steps), D(4)))
            steps = [run_wu(1, 500), run_int(2, 3000, easy * 0.95, easy * 1.05), run_cd(3, 500)]
            workouts.append((_wkt("run", f"{tag} Pre-Race Activation 4km",
                f"Easy pre-race | {ms_to_pace(easy)}/km", steps, 4000), D(4)))
            steps = [swim_wu(1, 200), swim_int(2, 400), swim_cd(3, 100)]
            workouts.append((_wkt("swim", f"{tag} Pre-Race Swim 700m",
                "Easy pre-race swim", steps, 700), D(4)))
            continue

        # ─────────────────────────── TAPER ───────────────────────────────────
        if is_taper:
            # Bike A — short Z3 activation (Tue)
            m = max(30, int(45 * vol))
            steps = [bike_wu(1, 10), bike_int(2, m, *Z3), bike_cd(3, 5)]
            workouts.append((_wkt("bike", f"{tag} Taper Z3 {m}min @{Z3[0]}-{Z3[1]}W",
                f"FTP={ftp}W | taper activation", steps), D(1)))
            # Bike B — easy spin (Fri)
            m2 = max(20, int(30 * vol))
            steps = [bike_wu(1, 10), bike_int(2, m2, *Z2), bike_cd(3, 5)]
            workouts.append((_wkt("bike", f"{tag} Taper Spin {m2}min @{Z2[0]}-{Z2[1]}W",
                f"FTP={ftp}W | taper spin", steps), D(4)))
            # Run A — easy (Wed)
            km = max(5, int(8 * vol))
            steps = [run_wu(1, 500), run_int(2, km * 1000, z2_run * 0.97, z2_run * 1.03), run_cd(3, 500)]
            workouts.append((_wkt("run", f"{tag} Taper Run {km}km @{ms_to_pace(z2_run)}/km",
                "Taper easy run", steps, (km + 1) * 1000), D(2)))
            # Run B — very easy (Sun)
            km2 = max(4, int(6 * vol))
            steps = [run_wu(1, 500), run_int(2, km2 * 1000, easy * 0.97, easy * 1.03), run_cd(3, 500)]
            workouts.append((_wkt("run", f"{tag} Taper Easy {km2}km @{ms_to_pace(easy)}/km",
                "Taper recovery run", steps, (km2 + 1) * 1000), D(6)))
            # Swim A — endurance (Thu)
            dist_a = max(800, round(int(prof["swim_m"] * 0.4 * vol) / 100) * 100)
            wu_d = min(300, dist_a // 4); main_d = max(200, dist_a - wu_d - 100)
            steps = [swim_wu(1, wu_d), swim_int(2, main_d), swim_cd(3, 100)]
            workouts.append((_wkt("swim", f"{tag} Taper Swim {dist_a}m",
                f"Taper swim {dist_a}m", steps, dist_a), D(3)))
            # Swim B — short pre-race (Fri, same day as Bike B)
            dist_b = max(400, round(int(prof["swim_m"] * 0.25 * vol) / 100) * 100)
            wu_d = min(200, dist_b // 4); main_d = max(200, dist_b - wu_d - 100)
            steps = [swim_wu(1, wu_d), swim_int(2, main_d), swim_cd(3, 100)]
            workouts.append((_wkt("swim", f"{tag} Taper Pre-Race Swim {dist_b}m",
                f"Taper swim {dist_b}m", steps, dist_b), D(4)))
            continue

        # ─────────────────────────── BASE + BUILD ────────────────────────────

        swim_base = int(prof["swim_m"] * 0.6 * vol)

        # ── SWIM A — technique/intervals (Mon D0) — 100m intervals, 20s rest ───
        dist_a = max(600, round(int(swim_base * 0.55) / 100) * 100)
        wu_d = min(300, dist_a // 4); main_d = max(200, dist_a - wu_d - 100)
        int_steps, next_o, n_int, each_d = swim_set(2, main_d, 100, 20)
        workouts.append((_wkt("swim", f"{tag} Swim Tech {dist_a}m",
            f"Technique & drills {dist_a}m | {n_int}×{each_d}m + 20s rest",
            [swim_wu(1, wu_d)] + int_steps + [swim_cd(next_o, 100)], dist_a), D(0)))

        # ── SWIM B — endurance (Thu D3) — 200m intervals, 15s rest ──────────────
        dist_b = max(800, round(int(swim_base * 0.75) / 100) * 100)
        wu_d = min(400, dist_b // 4); main_d = max(300, dist_b - wu_d - 100)
        int_steps, next_o, n_int, each_d = swim_set(2, main_d, 200, 15)
        workouts.append((_wkt("swim", f"{tag} Swim Endurance {dist_b}m",
            f"Endurance {dist_b}m | {n_int}×{each_d}m + 15s rest",
            [swim_wu(1, wu_d)] + int_steps + [swim_cd(next_o, 100)], dist_b), D(3)))

        # ── SWIM C — race-sim (Fri D4) — 400m intervals, 10s rest — BUILD only ──
        if is_build:
            dist_c = max(400, round(int(prof["swim_m"] * 0.85 * vol) / 100) * 100)
            wu_d = min(200, dist_c // 5); main_d = max(200, dist_c - wu_d - 100)
            int_steps, next_o, n_int, each_d = swim_set(2, main_d, 400, 10)
            workouts.append((_wkt("swim", f"{tag} Swim Race-Sim {dist_c}m",
                f"Race-pace {dist_c}m | {n_int}×{each_d}m + 10s rest",
                [swim_wu(1, wu_d)] + int_steps + [swim_cd(next_o, 100)], dist_c), D(4)))

        # ── BIKE A — main quality session (Tue D1) ────────────────────────────
        q = wk % 3
        if q == 0:
            steps = [bike_wu(1, 15),
                     bike_int(2, 20, *Z4), bike_rec(3, 5, *Z1),
                     bike_int(4, 20, *Z4), bike_rec(5, 5, *Z1),
                     bike_int(6, 15, *Z4), bike_cd(7, 10)]
            workouts.append((_wkt("bike", f"{tag} Threshold 3x20min @{Z4[0]}-{Z4[1]}W",
                f"FTP={ftp}W | threshold", steps), D(1)))
        elif q == 1:
            m = max(45, int(80 * vol))
            steps = [bike_wu(1, 15), bike_int(2, m, *ZR), bike_cd(3, 10)]
            workouts.append((_wkt("bike", f"{tag} Race Sim {m}min @{ZR[0]}-{ZR[1]}W",
                f"FTP={ftp}W | race simulation", steps), D(1)))
        else:
            if is_build:
                steps = [bike_wu(1, 15),
                         bike_int(2, 5, *Z5), bike_rec(3, 3, *Z1),
                         bike_int(4, 5, *Z5), bike_rec(5, 3, *Z1),
                         bike_int(6, 5, *Z5), bike_rec(7, 3, *Z1),
                         bike_int(8, 5, *Z5), bike_cd(9, 10)]
                workouts.append((_wkt("bike", f"{tag} VO2max 4x5min @{Z5[0]}-{Z5[1]}W",
                    f"FTP={ftp}W | VO2max", steps), D(1)))
            else:
                m = max(40, int(60 * vol))
                steps = [bike_wu(1, 10), bike_int(2, m, *Z3), bike_cd(3, 5)]
                workouts.append((_wkt("bike", f"{tag} Tempo {m}min @{Z3[0]}-{Z3[1]}W",
                    f"FTP={ftp}W | tempo Z3", steps), D(1)))

        # ── BIKE B — Z2 endurance (Thu D3, same day as Swim B) ───────────────
        m = max(45, int(70 * vol))
        steps = [bike_wu(1, 10), bike_int(2, m, *Z2), bike_cd(3, 5)]
        workouts.append((_wkt("bike", f"{tag} Z2 Endurance {m}min @{Z2[0]}-{Z2[1]}W",
            f"FTP={ftp}W | aerobic base", steps), D(3)))

        # ── BIKE C — long ride (Sat D5) — BUILD only ─────────────────────────
        if is_build:
            m_long = max(90, int(150 * vol))
            steps = [bike_wu(1, 15), bike_int(2, m_long, *Z2), bike_cd(3, 10)]
            workouts.append((_wkt("bike", f"{tag} Long Ride {m_long}min @{Z2[0]}-{Z2[1]}W",
                f"FTP={ftp}W | long Z2", steps), D(5)))

        # ── RUN A — tempo (Wed D2) ────────────────────────────────────────────
        km = min(12, max(6, int(10 * vol)))
        steps = [run_wu(1, 1000), run_int(2, km * 1000, race_p * 0.98, race_p * 1.02), run_cd(3, 1000)]
        workouts.append((_wkt("run", f"{tag} Tempo {km}km @{ms_to_pace(race_p)}/km",
            f"Race pace run {ms_to_pace(race_p)}/km", steps, (km + 2) * 1000), D(2)))

        # ── RUN B — long run (Sun D6) ─────────────────────────────────────────
        max_long = 18 if distance in ("full", "70.3") else 12
        km_long = min(max_long, max(8, int(prof["run_km"] * 0.85 * vol)))
        steps = [run_wu(1, 500), run_int(2, km_long * 1000, z2_run * 0.96, z2_run * 1.04), run_cd(3, 500)]
        workouts.append((_wkt("run", f"{tag} Long Run {km_long}km @{ms_to_pace(z2_run)}/km",
            "Long Z2 run", steps, (km_long + 1) * 1000), D(6)))

        # ── RUN C — easy recovery (Fri D4, same day as Swim C) — BUILD only ──
        if is_build:
            km_easy = max(6, int(9 * vol))
            steps = [run_wu(1, 500), run_int(2, km_easy * 1000, easy * 0.97, easy * 1.03), run_cd(3, 500)]
            workouts.append((_wkt("run", f"{tag} Easy Run {km_easy}km @{ms_to_pace(easy)}/km",
                "Easy recovery run", steps, (km_easy + 1) * 1000), D(4)))

    return workouts


def generate_bridge_block(race_date, distance, ftp, run_pace_ms, prefix,
                          gap_weeks, race_bike_pct=None, vol_scale=1.0):
    """
    Condensed block for a race that closely follows a previous race (gap_weeks 1-5).
    Based on: TrainingPeaks, Purple Patch (Matt Dixon), Joe Friel.

    Phase mapping by gap:
      1w: [race]
      2w: [recovery, race+activation]
      3w: [recovery, taper, race]
      4w: [recovery, sharpen, taper, race]
      5w: [recovery, sharpen, sharpen, taper, race]

    Recovery  (vol=0.45): Z1/Z2 only — swim, easy spin, easy run. No intensity.
    Sharpening (vol=0.75): Z2 base + race-pace activation (nervous system reset).
    Taper     (vol=0.60): Same structure as generate_race_block taper.
    Race: Standard pre-race sessions + activation run Tue (gap<=2, "Day 8" reset).
    """
    if ftp <= 0:
        raise ValueError(f"FTP must be > 0 (got {ftp})")
    prof = PROFILES[distance]
    rp   = race_bike_pct if race_bike_pct is not None else prof["race_bike_pct"]
    if rp > 0.95:
        rp = 0.95

    z      = lambda lo, hi: (round(ftp * lo), round(ftp * hi))
    Z1     = z(0.40, 0.55); Z2 = z(0.60, 0.72); Z3 = z(0.76, 0.87)
    ZR     = z(rp - 0.03, rp + 0.03)
    easy   = run_pace_ms * 0.85
    z2_run = run_pace_ms * 0.93
    race_p = run_pace_ms

    plan_start = race_date - timedelta(weeks=gap_weeks)
    workouts   = []

    for wk in range(1, gap_weeks + 1):
        wk_start    = plan_start + timedelta(weeks=wk - 1)
        is_race     = (wk == gap_weeks)
        is_taper    = not is_race and gap_weeks >= 3 and (wk == gap_weeks - 1)
        is_sharpen  = not is_race and not is_taper and wk > 1
        is_recovery = (wk == 1) and gap_weeks >= 2

        def D(offset, _ws=wk_start): return (_ws + timedelta(days=offset)).strftime("%Y-%m-%d")
        tag = f"{prefix}-T{wk:02d}"

        # ── RACE WEEK ──────────────────────────────────────────────────────────
        if is_race:
            # Activation run Tue D(1) — "Day 8" nervous system reset (gap<=2 only)
            if gap_weeks <= 2:
                steps = [run_wu(1, 300),
                         run_int(2, 1500, race_p * 0.95, race_p * 1.05),
                         run_int(3, 1500, race_p * 0.95, race_p * 1.05),
                         run_cd(4, 300)]
                workouts.append((_wkt("run", f"{tag} Activation 3.6km @{ms_to_pace(race_p)}/km",
                    "Nervous system reset — short race-pace strides", steps, 3600), D(1)))
            # Standard pre-race sessions Fri D(4)
            steps = [bike_wu(1, 5), bike_int(2, 15, *Z2), bike_cd(3, 5)]
            workouts.append((_wkt("bike", f"{tag} Pre-Race Check 20min",
                f"FTP={ftp}W | pre-race activation", steps), D(4)))
            steps = [run_wu(1, 500), run_int(2, 3000, easy * 0.95, easy * 1.05), run_cd(3, 500)]
            workouts.append((_wkt("run", f"{tag} Pre-Race Activation 4km",
                f"Easy pre-race | {ms_to_pace(easy)}/km", steps, 4000), D(4)))
            steps = [swim_wu(1, 200), swim_int(2, 400), swim_cd(3, 100)]
            workouts.append((_wkt("swim", f"{tag} Pre-Race Swim 700m",
                "Easy pre-race swim", steps, 700), D(4)))
            continue

        # ── TAPER WEEK ─────────────────────────────────────────────────────────
        if is_taper:
            vol = 0.6 * vol_scale
            m = max(30, int(45 * vol))
            steps = [bike_wu(1, 10), bike_int(2, m, *Z3), bike_cd(3, 5)]
            workouts.append((_wkt("bike", f"{tag} Taper Z3 {m}min @{Z3[0]}-{Z3[1]}W",
                f"FTP={ftp}W | taper activation", steps), D(1)))
            m2 = max(20, int(30 * vol))
            steps = [bike_wu(1, 10), bike_int(2, m2, *Z2), bike_cd(3, 5)]
            workouts.append((_wkt("bike", f"{tag} Taper Spin {m2}min @{Z2[0]}-{Z2[1]}W",
                f"FTP={ftp}W | taper spin", steps), D(4)))
            km = max(5, int(8 * vol))
            steps = [run_wu(1, 500), run_int(2, km * 1000, z2_run * 0.97, z2_run * 1.03), run_cd(3, 500)]
            workouts.append((_wkt("run", f"{tag} Taper Run {km}km @{ms_to_pace(z2_run)}/km",
                "Taper easy run", steps, (km + 1) * 1000), D(2)))
            km2 = max(4, int(6 * vol))
            steps = [run_wu(1, 500), run_int(2, km2 * 1000, easy * 0.97, easy * 1.03), run_cd(3, 500)]
            workouts.append((_wkt("run", f"{tag} Taper Easy {km2}km @{ms_to_pace(easy)}/km",
                "Taper recovery run", steps, (km2 + 1) * 1000), D(6)))
            dist_a = max(800, round(int(prof["swim_m"] * 0.4 * vol) / 100) * 100)
            wu_d = min(300, dist_a // 4); main_d = max(200, dist_a - wu_d - 100)
            steps = [swim_wu(1, wu_d), swim_int(2, main_d), swim_cd(3, 100)]
            workouts.append((_wkt("swim", f"{tag} Taper Swim {dist_a}m",
                f"Taper swim {dist_a}m", steps, dist_a), D(3)))
            dist_b = max(400, round(int(prof["swim_m"] * 0.25 * vol) / 100) * 100)
            wu_d = min(200, dist_b // 4); main_d = max(200, dist_b - wu_d - 100)
            steps = [swim_wu(1, wu_d), swim_int(2, main_d), swim_cd(3, 100)]
            workouts.append((_wkt("swim", f"{tag} Taper Pre-Race Swim {dist_b}m",
                f"Taper swim {dist_b}m", steps, dist_b), D(4)))
            continue

        # ── SHARPENING WEEK ────────────────────────────────────────────────────
        if is_sharpen:
            vol = 0.75 * vol_scale
            # Activation run — race-pace strides (Tue)
            steps = [run_wu(1, 500),
                     run_int(2, 3000, race_p * 0.97, race_p * 1.03),
                     run_int(3, 3000, race_p * 0.97, race_p * 1.03),
                     run_cd(4, 500)]
            workouts.append((_wkt("run", f"{tag} Activation 7km @{ms_to_pace(race_p)}/km",
                "Nervous system reset — race-pace strides", steps, 7000), D(1)))
            # Swim endurance (Wed)
            dist_sw = max(1000, round(int(prof["swim_m"] * 0.65 * vol) / 100) * 100)
            wu_d = min(300, dist_sw // 4); main_d = max(300, dist_sw - wu_d - 100)
            int_steps, next_o, n_int, each_d = swim_set(2, main_d, 200, 15)
            workouts.append((_wkt("swim", f"{tag} Swim Endurance {dist_sw}m",
                f"Endurance {dist_sw}m | {n_int}×{each_d}m + 15s rest",
                [swim_wu(1, wu_d)] + int_steps + [swim_cd(next_o, 100)], dist_sw), D(2)))
            # Bike race sim (Thu)
            m = max(40, int(60 * vol))
            steps = [bike_wu(1, 15), bike_int(2, m, *ZR), bike_cd(3, 10)]
            workouts.append((_wkt("bike", f"{tag} Race Sim {m}min @{ZR[0]}-{ZR[1]}W",
                f"FTP={ftp}W | race pace sharpening", steps), D(3)))
            # Easy Z2 bike (Sat)
            m2 = max(45, int(70 * vol))
            steps = [bike_wu(1, 10), bike_int(2, m2, *Z2), bike_cd(3, 5)]
            workouts.append((_wkt("bike", f"{tag} Z2 Endurance {m2}min @{Z2[0]}-{Z2[1]}W",
                f"FTP={ftp}W | aerobic maintenance", steps), D(5)))
            # Long run (Sun)
            km = min(14, max(10, int(prof["run_km"] * 0.75 * vol)))
            steps = [run_wu(1, 500), run_int(2, km * 1000, z2_run * 0.96, z2_run * 1.04), run_cd(3, 500)]
            workouts.append((_wkt("run", f"{tag} Long Run {km}km @{ms_to_pace(z2_run)}/km",
                "Long Z2 run", steps, (km + 1) * 1000), D(6)))
            continue

        # ── RECOVERY WEEK ──────────────────────────────────────────────────────
        if is_recovery:
            vol = 0.45 * vol_scale
            # Skip D(0) — may coincide with previous race day
            dist_sw = max(400, round(int(prof["swim_m"] * 0.3 * vol) / 100) * 100)
            wu_d = min(200, dist_sw // 4); main_d = max(200, dist_sw - wu_d - 100)
            steps = [swim_wu(1, wu_d), swim_int(2, main_d), swim_cd(3, 100)]
            workouts.append((_wkt("swim", f"{tag} Recovery Swim {dist_sw}m",
                "Easy recovery swim Z1/Z2", steps, dist_sw), D(1)))
            m = max(25, int(40 * vol))
            steps = [bike_wu(1, 10), bike_int(2, m, *Z1), bike_cd(3, 5)]
            workouts.append((_wkt("bike", f"{tag} Recovery Spin {m}min @{Z1[0]}-{Z1[1]}W",
                f"FTP={ftp}W | easy recovery Z1", steps), D(3)))
            km = max(4, int(7 * vol))
            steps = [run_wu(1, 500), run_int(2, km * 1000, easy * 0.95, easy * 1.05), run_cd(3, 500)]
            workouts.append((_wkt("run", f"{tag} Recovery Run {km}km @{ms_to_pace(easy)}/km",
                "Easy recovery run Z1/Z2", steps, (km + 1) * 1000), D(5)))

    return workouts

# ─── GARMIN RESET & UPLOAD ───────────────────────────────────────────────────

def clean_prefix(client, prefix):
    """Remove all workouts/schedules with given prefix. Safe full reset."""
    http = _http(client)
    print(f"  Cleaning '{prefix}' from calendar...")
    removed_s = 0
    today = date.today()
    for dm in range(-1, 14):  # -1 month back, 13 months ahead
        y = today.year + (today.month + dm - 1) // 12
        m = (today.month + dm - 1) % 12
        try:
            data = client.connectapi(f"/calendar-service/year/{y}/month/{m}")
            for item in data.get("calendarItems", []):
                if item.get("itemType") != "workout": continue
                if not item.get("title","").startswith(prefix): continue
                sid = item.get("id") or item.get("scheduleId")
                if sid:
                    try:
                        http.request("DELETE","connectapi",
                            f"/workout-service/schedule/{sid}", api=True)
                        removed_s += 1
                        time.sleep(0.08)
                    except Exception: pass
        except Exception: pass
    print(f"    Removed {removed_s} scheduled entries")

    print(f"  Cleaning '{prefix}' from library...")
    workouts = client.get_workouts(start=0, limit=500)
    to_del   = [w for w in workouts if w.get("workoutName","").startswith(prefix)]
    removed_l = 0
    for w in to_del:
        try:
            http.request("DELETE","connectapi",
                f"/workout-service/workout/{w['workoutId']}", api=True)
            removed_l += 1
            time.sleep(0.08)
        except Exception: pass
    print(f"    Removed {removed_l} library workouts")

def upload_workouts(client, workouts, dry_run=False):
    ok = fail = 0
    uploaded = []
    for wkt, date_str in sorted(workouts, key=lambda x: x[1]):
        name = wkt["workoutName"]
        if dry_run:
            print(f"    [DRY] {date_str}  {name}")
            ok += 1
            continue
        try:
            result = client.upload_workout(wkt)
            wid    = result.get("workoutId")
            client.schedule_workout(wid, date_str)
            uploaded.append({
                "name":       name,
                "workout_id": wid,
                "date":       date_str,
                "sport":      wkt["sportType"]["sportTypeKey"],
            })
            ok += 1
            time.sleep(0.25)
        except Exception as e:
            print(f"    ✗ {date_str}  {name}: {e}")
            fail += 1
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
    print(f"  Plan state saved → {path}")

# ─── INTERACTIVE CONFIG ───────────────────────────────────────────────────────

def interactive_config():
    print("═"*60)
    print("  TRIATHLON SEASON PLANNER")
    print("═"*60)
    print()

    ftp    = int(input("Your FTP in watts (from MyWhoosh/Garmin): ").strip())
    weight = float(input("Body weight in kg (e.g. 80): ").strip() or "75")
    cda    = float(input("CdA (m²) for bike power model (press Enter for 0.32): ").strip() or "0.32")
    run_pace = input("Default run pace MM:SS/km — press Enter to set per race via target time: ").strip()

    races = []
    print("\nEnter your races (press Enter with empty name when done):")
    print("Distances: 70.3 / full / olympic / sprint\n")

    i = 1
    while True:
        print(f"Race {i}:")
        name = input("  Short name/prefix (e.g. WARSAW, BERLIN): ").strip().upper()
        if not name:
            if not races:
                print("  Need at least one race!")
                continue
            break
        date_s = input("  Race date YYYY-MM-DD: ").strip()
        dist   = input("  Distance (70.3/full/olympic/sprint): ").strip()
        if dist not in PROFILES:
            print(f"  Unknown distance, using 70.3")
            dist = "70.3"
        target_time = input("  Target finish time H:MM:SS (or Enter to use default pace): ").strip()
        race = {"name": name, "date": date_s, "distance": dist}
        if target_time:
            race["target_time"] = target_time
        races.append(race)
        print(f"  ✓ Added {name} on {date_s} ({PROFILES[dist]['label']})\n")
        i += 1

    cfg = {"ftp": ftp, "weight_kg": weight, "cda": cda, "races": races}
    if run_pace:
        cfg["run_pace"] = run_pace
    return cfg

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Triathlon Season Planner — multi-race Garmin upload")
    p.add_argument("--config",   help="JSON config file with races")
    p.add_argument("--dry-run",  action="store_true", help="Preview without uploading")
    p.add_argument("--reset",    action="store_true", help="Full reset each prefix before upload")
    p.add_argument("--ftp",       type=int,   help="FTP override in watts")
    p.add_argument("--auto-ftp",  action="store_true",
                   help="Read FTP from Garmin Connect (login required)")
    p.add_argument("--run-pace",  help="Run pace override MM:SS")
    p.add_argument("--vol-scale", type=float, default=1.0,
                   help="Volume multiplier (default: 1.0). Use strava_suggest.py to calibrate.")
    args = p.parse_args()

    # Load config
    if args.config:
        try:
            with open(args.config) as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            sys.exit(f"ERROR: Cannot read config '{args.config}': {e}")
        _validate_config(cfg, args.config)
        print(f"Loaded config: {args.config}")
    else:
        cfg = interactive_config()

    # CLI overrides
    if args.ftp:       cfg["ftp"]       = args.ftp
    if args.run_pace:  cfg["run_pace"]  = args.run_pace

    if args.auto_ftp and not args.ftp:
        print("Logging in to Garmin to read FTP...")
        _c = login()
        garmin_ftp = get_garmin_ftp(_c)
        if garmin_ftp:
            cfg["ftp"] = garmin_ftp
            print(f"  Auto FTP from Garmin: {garmin_ftp}W\n")
        else:
            print("  ⚠ Could not read FTP from Garmin — using config value.\n")

    ftp       = cfg["ftp"]
    weight    = cfg.get("weight_kg", 75)
    cda       = cfg.get("cda", 0.32)
    races     = cfg["races"]
    vol_scale = args.vol_scale if args.vol_scale != 1.0 else cfg.get("vol_scale", 1.0)

    if ftp <= 0:
        p.error(f"FTP must be > 0 (got {ftp})")
    if weight <= 0:
        p.error(f"weight must be > 0 (got {weight})")
    if cda <= 0:
        p.error(f"cda must be > 0 (got {cda})")
    if not (0.1 <= vol_scale <= 3.0):
        p.error(f"vol_scale must be in [0.1, 3.0] (got {vol_scale})")

    # Global run pace — optional if all races define target_time
    global_run_pace_ms = pace_to_ms(cfg["run_pace"]) if "run_pace" in cfg else None

    # Check for date conflicts between race blocks
    all_dates = defaultdict(list)
    all_workouts_by_prefix = {}
    race_configs = {}

    print(f"\n{'═'*60}")
    print(f"  SEASON PLAN SUMMARY")
    print(f"{'═'*60}")
    print(f"  FTP:       {ftp}W")
    if global_run_pace_ms:
        print(f"  Run pace:  {cfg['run_pace']}/km  (global default)")
    print(f"  Weight:    {weight}kg  |  CdA: {cda} m²")
    print(f"  Races:     {len(races)}")
    if vol_scale != 1.0:
        print(f"  Vol scale: {vol_scale}× (use strava_suggest.py to recalibrate)")
    print()

    # Generate all blocks (sorted by date to detect inter-race gaps)
    total_workouts = 0
    prev_race_date = None
    for race in sorted(races, key=lambda r: r["date"]):
        rdate  = date.fromisoformat(race["date"])
        dist   = race["distance"]
        prefix = race["name"].upper()
        _validate_prefix(prefix)
        prof          = PROFILES[dist]
        full_weeks    = prof["weeks"]
        today         = date.today()
        if prev_race_date is not None:
            gap_weeks  = (rdate - prev_race_date).days // 7
            first_race = False
        else:
            avail      = (rdate - today).days // 7
            gap_weeks  = avail if avail < full_weeks else None
            first_race = True
        use_bridge    = not first_race and gap_weeks is not None and gap_weeks <= 5
        use_truncated = gap_weeks is not None and not use_bridge
        block_weeks   = gap_weeks if (use_bridge or use_truncated) else full_weeks
        start         = rdate - timedelta(weeks=block_weeks)

        target_time = race.get("target_time")
        if target_time:
            splits = calc_splits(dist, target_time, ftp, weight, cda,
                                 custom_swim_min=race.get("swim_min"),
                                 custom_t1t2_min=race.get("t1t2_min"))
            run_pace_ms    = splits["run_pace_ms"]
            race_bike_pct  = splits["bike_pct_ftp"]
        else:
            if global_run_pace_ms is None:
                raise ValueError(
                    f"Race {prefix}: no target_time and no global run_pace defined.")
            run_pace_ms   = global_run_pace_ms
            race_bike_pct = None

        print(f"  ▸ {prefix:12s}  {race['date']}  {prof['label']}")
        if use_bridge:
            print(f"    Block: {start} → {race['date']}  ({block_weeks}w bridge — after {prev_race_date})")
            if gap_weeks <= 2:
                print(f"    ⚠ Only {gap_weeks} week(s) after previous race — 2nd result may be 5-10% slower")
        elif use_truncated and first_race:
            print(f"    Block: {start} → {race['date']}  ({block_weeks}w — truncated from {full_weeks})")
            print(f"    ⚠ Plan truncated: only {block_weeks} week(s) until race (full plan: {full_weeks} weeks)")
        else:
            print(f"    Block: {start} → {race['date']}  ({block_weeks} weeks)")

        if target_time:
            s = splits
            pct_str = f"{s['bike_pct_ftp']*100:.0f}% FTP"
            warn = "  ⚠ >100% FTP — unrealistic!" if s['bike_pct_ftp'] > 1.0 else ""
            print(f"    Target: {target_time}  →  splits:")
            print(f"      Swim:     {_fmt_hm(s['swim_min'])}  @ {s['swim_pace']}")
            print(f"      T1+T2:    {_fmt_hm(s['t1t2_min'])}")
            print(f"      Bike:     {_fmt_hm(s['bike_min'])}  @ {s['bike_kmh']} km/h  →  ~{s['bike_watts']}W ({pct_str}){warn}")
            print(f"      Run:      {_fmt_hm(s['run_min'])}  @ {s['run_pace_str']}/km")

        if use_bridge:
            wkts = generate_bridge_block(rdate, dist, ftp, run_pace_ms, prefix,
                                          gap_weeks, race_bike_pct=race_bike_pct,
                                          vol_scale=vol_scale)
        else:
            wkts = generate_race_block(rdate, dist, ftp, run_pace_ms, prefix,
                                        race_bike_pct=race_bike_pct, vol_scale=vol_scale,
                                        override_weeks=gap_weeks if use_truncated else None)
        all_workouts_by_prefix[prefix] = wkts
        total_workouts += len(wkts)

        race_configs[prefix] = {
            "race_date":    race["date"],
            "distance":     dist,
            "ftp":          ftp,
            "weight_kg":    weight,
            "cda":          cda,
            "vol_scale":    vol_scale,
            "run_pace_ms":  run_pace_ms,
            "run_pace_str": ms_to_pace(run_pace_ms),
        }
        if target_time:
            race_configs[prefix]["target_time"]   = target_time
            race_configs[prefix]["race_bike_pct"] = race_bike_pct

        by_sport = defaultdict(int)
        for wkt, _ in wkts:
            by_sport[wkt["sportType"]["sportTypeKey"]] += 1
        print(f"    Sessions: {len(wkts)} total — "
              f"🏃{by_sport['running']} run  "
              f"🏊{by_sport['swimming']} swim  "
              f"🚲{by_sport['cycling']} bike")
        print()

        for wkt, d in wkts:
            all_dates[d].append(prefix)
        prev_race_date = rdate

    # Warn about overlapping dates
    overlaps = {d:ps for d,ps in all_dates.items() if len(ps) > 3}
    if overlaps:
        print(f"  ⚠ Date overlaps between race blocks (consider different weeks):")
        for d, ps in sorted(overlaps.items())[:10]:
            print(f"    {d}: {', '.join(ps)}")
        print()

    print(f"  Total workouts: {total_workouts}")
    print(f"  Upload to Garmin: {'DRY RUN' if args.dry_run else 'YES'}")
    print(f"  Full reset:       {'YES (per prefix)' if args.reset else 'NO'}")
    print(f"{'═'*60}\n")

    if args.dry_run:
        print("DRY RUN — showing first 10 workouts per race:\n")
        for prefix, wkts in all_workouts_by_prefix.items():
            print(f"  {prefix}:")
            for wkt, d in sorted(wkts, key=lambda x:x[1])[:10]:
                sport = wkt["sportType"]["sportTypeKey"][0].upper()
                print(f"    {d}  [{sport}] {wkt['workoutName']}")
            print()
        return

    confirm = input("Upload all to Garmin Connect? (yes/no): ").strip().lower()
    if confirm not in ("yes","y"):
        print("Aborted.")
        return

    print("\nLogging in to Garmin Connect...")
    client = login()

    total_ok = total_fail = 0

    for race in races:
        prefix = race["name"]
        wkts   = all_workouts_by_prefix[prefix]
        print(f"\n{'─'*50}")
        print(f"  RACE: {prefix}  ({race['date']}  {race['distance']})")
        print(f"{'─'*50}")

        if args.reset:
            print(f"  Resetting '{prefix}'...")
            clean_prefix(client, prefix)

        print(f"  Uploading {len(wkts)} workouts...")
        ok, fail, uploaded = upload_workouts(client, wkts)
        total_ok   += ok
        total_fail += fail
        print(f"  ✓ Done: {ok} uploaded" + (f" | {fail} failed" if fail else ""))
        save_plan_state(prefix, race_configs[prefix], uploaded)

    print(f"\n{'═'*60}")
    print(f"  SEASON UPLOAD COMPLETE")
    print(f"  Total uploaded: {total_ok}" + (f" | Errors: {total_fail}" if total_fail else " — no errors"))
    print(f"  View at: https://connect.garmin.com/app/calendar")
    print(f"{'═'*60}\n")

    # ── MyWhoosh / Zwift .zwo files ───────────────────────────────────────────
    zwo_ans = input("Generate .zwo files for MyWhoosh/Zwift? (yes/no): ").strip().lower()
    if zwo_ans in ("yes", "y"):
        try:
            from mywhoosh_season import generate_for_distance
            print()
            for race in races:
                prefix   = race["name"]
                distance = race["distance"]
                out      = f"./mywhoosh_{prefix.lower()}"
                generate_for_distance(prefix, distance, ftp, out)
        except ImportError:
            print("  mywhoosh_season.py not found — place it in the same folder.")

if __name__ == "__main__":
    main()
