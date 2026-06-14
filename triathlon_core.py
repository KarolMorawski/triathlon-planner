#!/usr/bin/env python3
"""
triathlon_core.py — shared utilities for the triathlon training planner suite.

Exports
-------
Constants:       STATE_DIR, TOKEN_FILE
Validation:      validate_prefix_pl, validate_prefix_en
State I/O:       load_state_pl, load_state_en
Garmin login:    login, login_pl, login_en
Garmin library:  get_all_workouts, clean_calendar_prefix, clean_library_prefix
Race profiles:   PROFILES, SPLIT_RATIOS
Split calc:      calc_splits, pace_to_ms, ms_to_pace, _parse_hms, _fmt_hm
Step factories:  _no_tgt, _pwr_tgt, _pace_tgt, _step,
                 bike_wu, bike_cd, bike_int, bike_rec,
                 run_wu, run_cd, run_int,
                 swim_wu, swim_cd, swim_int, swim_rest, swim_set, _r25
Compat aliases:  _no_target, _power_target, _pace_target,
                 _bwu, _bcd, _bint, _brec,
                 _rwu, _rcd, _rint,
                 _swu, _scd, _sint, _srest, _swim_set
"""

import json
import logging
import os
import re
import sys
import time
from datetime import date

log = logging.getLogger(__name__)

# ─── CONSTANTS ────────────────────────────────────────────────────────────────

STATE_DIR  = os.path.expanduser("~/.triathlon_plans")
TOKEN_FILE = os.path.expanduser("~/.garmin_token")

# ─── PREFIX VALIDATION ────────────────────────────────────────────────────────

_PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")

def validate_prefix_pl(p):
    """Reject prefixes that could escape STATE_DIR or contain unsafe characters."""
    if not _PREFIX_RE.match(p):
        sys.exit(f"BŁĄD: Niepoprawny prefix '{p}'. Dozwolone: A-Z, 0-9, _, - (musi zaczynać się od znaku alfanumerycznego).")

def validate_prefix_en(p):
    """Reject prefixes that could escape STATE_DIR or contain unsafe characters."""
    if not _PREFIX_RE.match(p):
        sys.exit(f"ERROR: Invalid prefix '{p}'. Allowed: A-Z, 0-9, _, - (must start alphanumeric).")

# ─── STATE I/O ────────────────────────────────────────────────────────────────

def load_state_pl(prefix):
    path = os.path.join(STATE_DIR, f"{prefix}.json")
    if not os.path.exists(path):
        sys.exit(
            f"BŁĄD: Brak pliku stanu dla '{prefix}'  ({path})\n"
            f"  Uruchom najpierw season_plan.py lub generate_plan.py."
        )
    with open(path) as f:
        return json.load(f)

def load_state_en(prefix):
    path = os.path.join(STATE_DIR, f"{prefix}.json")
    if not os.path.exists(path):
        sys.exit(
            f"ERROR: No saved plan for '{prefix}'  ({path})\n"
            f"  Run season_plan.py or generate_plan_en.py first."
        )
    with open(path) as f:
        return json.load(f)

# ─── GARMIN LOGIN ─────────────────────────────────────────────────────────────

_LOGIN_EN = dict(
    no_garminconnect="ERROR: garminconnect not installed.\n  Fix: pip install garminconnect",
    token_expired="  Cached token expired or invalid — fresh login required.",
    token_loaded="✓ Logged in to Garmin Connect (cached token)\n",
    token_saved="✓ Logged in to Garmin Connect (token saved to {TOKEN_FILE})\n",
    email_prompt="Garmin email: ",
    password_prompt="Garmin password: ",
    mfa_prompt="MFA/2FA code: ",
)

_LOGIN_PL = dict(
    no_garminconnect="BŁĄD: garminconnect nie jest zainstalowany.\n  pip install garminconnect",
    token_expired="  Token wygasł — wymagane ponowne logowanie.",
    token_loaded="✓ Zalogowano do Garmin Connect (token)\n",
    token_saved="✓ Zalogowano do Garmin Connect (token zapisany do {TOKEN_FILE})\n",
    email_prompt="Email Garmin: ",
    password_prompt="Hasło Garmin: ",
    mfa_prompt="Kod MFA: ",
)


def login(msgs=None):
    if msgs is None:
        msgs = _LOGIN_EN
    try:
        from garminconnect import Garmin
    except ImportError:
        sys.exit(msgs["no_garminconnect"])
    import getpass
    if os.path.isfile(TOKEN_FILE):
        try:
            client = Garmin()
            with open(TOKEN_FILE) as f:
                client.login(tokenstore=f.read())
            print(msgs["token_loaded"])
            return client
        except Exception:
            print(msgs["token_expired"])
    email    = input(msgs["email_prompt"]).strip()
    password = getpass.getpass(msgs["password_prompt"])
    client   = Garmin(email=email, password=password, return_on_mfa=True)
    result, state = client.login()
    if result == "needs_mfa":
        client.resume_login(state, input(msgs["mfa_prompt"]).strip())
    with open(TOKEN_FILE, "w") as f:
        f.write(client.client.dumps())
    os.chmod(TOKEN_FILE, 0o600)
    print(msgs["token_saved"].format(TOKEN_FILE=TOKEN_FILE))
    return client


def login_pl(): return login(_LOGIN_PL)
def login_en(): return login(_LOGIN_EN)

# ─── GARMIN LIBRARY ───────────────────────────────────────────────────────────

def get_all_workouts(client, page=200, cap=5000):
    """Page through the whole Garmin workout library.

    A single client.get_workouts() call caps at 500 results, but the library
    can hold more — a one-shot fetch silently misses the tail, so stale
    prefixed workouts survive a --reset and reappear as duplicates on
    re-upload. Loop until a short page (or the safety cap) is hit.
    """
    out, start = [], 0
    while len(out) < cap:
        batch = client.get_workouts(start=start, limit=page)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < page:
            break
        start += page
    return out


def clean_calendar_prefix(client, prefix, sleep_s=0.1, month_range=range(-1, 14)):
    """Delete calendar schedules whose title starts with `prefix`.

    Scans `month_range` months around today (Garmin month is 0-indexed).
    Returns (removed, failed): `failed` counts DELETEs that errored — each one
    leaves an orphan calendar entry, so callers should surface a non-zero count.
    A month that can't even be read is logged (not silently swallowed)."""
    http = client.client
    today = date.today()
    removed = failed = 0
    for dm in month_range:
        y = today.year + (today.month + dm - 1) // 12
        m = (today.month + dm - 1) % 12
        try:
            data = client.connectapi(f"/calendar-service/year/{y}/month/{m}")
            for item in data.get("calendarItems", []):
                if item.get("itemType") != "workout":
                    continue
                if not item.get("title", "").startswith(prefix):
                    continue
                sid = item.get("id") or item.get("scheduleId")
                if not sid:
                    continue
                try:
                    http.request("DELETE", "connectapi",
                                 f"/workout-service/schedule/{sid}", api=True)
                    removed += 1
                    time.sleep(sleep_s)
                except Exception as exc:
                    failed += 1
                    log.warning("Failed to delete schedule %s (%s/%s): %s", sid, y, m, exc)
        except Exception as exc:
            log.warning("Failed to read calendar %s/%s for cleanup of %r: %s", y, m, prefix, exc)
    return removed, failed


def clean_library_prefix(client, prefix, sleep_s=0.1):
    """Delete library workouts whose name starts with `prefix` (paginated).

    Returns (removed, failed): `failed` counts DELETEs that errored (orphans)."""
    http = client.client
    to_del = [w for w in get_all_workouts(client)
              if w.get("workoutName", "").startswith(prefix)]
    removed = failed = 0
    for w in to_del:
        try:
            http.request("DELETE", "connectapi",
                         f"/workout-service/workout/{w['workoutId']}", api=True)
            removed += 1
            time.sleep(sleep_s)
        except Exception as exc:
            failed += 1
            log.warning("Failed to delete library workout %s (%s): %s",
                        w.get("workoutId"), w.get("workoutName"), exc)
    return removed, failed

# ─── TARGET TYPES ─────────────────────────────────────────────────────────────
# CONFIRMED via Garmin API inspection:
#   id=1  no.target      → no intensity target (warmup/cooldown)
#   id=2  power.zone     → absolute watts (cycling intervals)
#   id=6  pace.zone      → m/s (running)

def _no_tgt():
    return {"workoutTargetTypeId":1,"workoutTargetTypeKey":"no.target","displayOrder":1}
def _pwr_tgt(lo_w, hi_w):
    return {"workoutTargetTypeId":2,"workoutTargetTypeKey":"power.zone","displayOrder":2}
def _pace_tgt(lo_ms, hi_ms):
    return {"workoutTargetTypeId":6,"workoutTargetTypeKey":"pace.zone","displayOrder":6}

# ─── STEP FACTORY ─────────────────────────────────────────────────────────────

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

_SWIM_EXTRA = {
    "strokeType":   {"strokeTypeId":0,"strokeTypeKey":None,"displayOrder":0},
    "equipmentType":{"equipmentTypeId":0,"equipmentTypeKey":None,"displayOrder":0},
}

def bike_wu(o, mins):                 return _step(o, 1,"warmup",   2, mins*60, _no_tgt())
def bike_cd(o, mins):                 return _step(o, 2,"cooldown", 2, mins*60, _no_tgt())
def bike_int(o, mins, lo_w, hi_w):   return _step(o, 3,"interval", 2, mins*60, _pwr_tgt(lo_w,hi_w), float(lo_w), float(hi_w))
def bike_rec(o, mins, lo_w, hi_w):   return _step(o, 4,"recovery", 2, mins*60, _pwr_tgt(lo_w,hi_w), float(lo_w), float(hi_w))

def run_wu(o, dist_m):                return _step(o, 1,"warmup",   3, dist_m, _no_tgt())
def run_cd(o, dist_m):                return _step(o, 2,"cooldown", 3, dist_m, _no_tgt())
def run_int(o, dist_m, lo_ms, hi_ms): return _step(o, 3,"interval", 3, dist_m, _pace_tgt(lo_ms,hi_ms), lo_ms, hi_ms)

def swim_wu(o, dist_m):  return _step(o, 1,"warmup",   3, dist_m, _no_tgt(), extra=_SWIM_EXTRA)
def swim_cd(o, dist_m):  return _step(o, 2,"cooldown", 3, dist_m, _no_tgt(), extra=_SWIM_EXTRA)
def swim_int(o, dist_m): return _step(o, 3,"interval", 3, dist_m, _no_tgt(), extra=_SWIM_EXTRA)
def swim_rest(o, secs):  return _step(o, 5,"rest",     2, secs,   _no_tgt(), extra=_SWIM_EXTRA)

_r25 = lambda x: max(25, round(x / 25) * 25)  # round to nearest pool length (25m)

def swim_set(start_order, total_dist, interval_dist, rest_secs):
    interval_dist = min(interval_dist, total_dist)
    n = max(1, round(total_dist / interval_dist))
    each = _r25(total_dist / n)
    steps, o = [], start_order
    for i in range(n):
        steps.append(swim_int(o, each)); o += 1
        if i < n - 1:
            steps.append(swim_rest(o, rest_secs)); o += 1
    return steps, o, n, each

# ─── COMPAT ALIASES (generate_plan.py naming convention) ─────────────────────

_no_target    = _no_tgt
_power_target = _pwr_tgt
_pace_target  = _pace_tgt
_bwu, _bcd, _bint, _brec = bike_wu, bike_cd, bike_int, bike_rec
_rwu, _rcd, _rint        = run_wu,  run_cd,  run_int
_swu, _scd, _sint, _srest = swim_wu, swim_cd, swim_int, swim_rest
_swim_set                 = swim_set

# ─── RACE PROFILES ────────────────────────────────────────────────────────────
# Single source of truth — distance facts + bike race intensity (% FTP).
# Canonical key for race bike intensity is `race_bike_pct` (used across all
# scripts); a long-standing duplicate dict in generate_plan.py called it
# `race_pace_pct` — now unified here.

PROFILES = {
    "70.3":    {"label":"Half Ironman 70.3",  "weeks":12, "swim_m":1900, "bike_km":90,  "run_km":21.1,  "race_bike_pct":0.82},
    "full":    {"label":"Full Ironman",       "weeks":16, "swim_m":3800, "bike_km":180, "run_km":42.2,  "race_bike_pct":0.72},
    "olympic": {"label":"Olympic Distance",   "weeks":10, "swim_m":1500, "bike_km":40,  "run_km":10,    "race_bike_pct":0.88},
    "quarter": {"label":"Quarter Ironman",    "weeks":9,  "swim_m":950,  "bike_km":45,  "run_km":10.55, "race_bike_pct":0.90},
    "sprint":  {"label":"Sprint Distance",    "weeks":8,  "swim_m":750,  "bike_km":20,  "run_km":5,     "race_bike_pct":0.95},
}

# Default split ratios (pct of active time after T1+T2) — based on age-group data
SPLIT_RATIOS = {
    "sprint":  {"t1t2_min":  5, "swim_pct": 0.13, "bike_pct": 0.47, "run_pct": 0.40},
    "quarter": {"t1t2_min":  6, "swim_pct": 0.12, "bike_pct": 0.51, "run_pct": 0.37},
    "olympic": {"t1t2_min":  7, "swim_pct": 0.12, "bike_pct": 0.52, "run_pct": 0.36},
    "70.3":    {"t1t2_min": 10, "swim_pct": 0.11, "bike_pct": 0.53, "run_pct": 0.36},
    "full":    {"t1t2_min": 12, "swim_pct": 0.11, "bike_pct": 0.52, "run_pct": 0.37},
}

# ─── PACE / TIME HELPERS ──────────────────────────────────────────────────────

def ms_to_pace(ms):
    """m/s → 'M:SS' pace per km."""
    spk = 1000.0 / ms; m = int(spk // 60); s = round(spk % 60)
    if s == 60:
        m += 1; s = 0
    return f"{m}:{s:02d}"

def pace_to_ms(s):
    """'M:SS' or 'MM:SS' pace per km → m/s."""
    p = s.strip().split(":")
    return 1000.0 / (int(p[0]) * 60 + int(p[1]))

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

# ─── TARGET-TIME SPLIT CALCULATOR ─────────────────────────────────────────────

def calc_splits(distance, target_time_str, ftp, weight_kg=75, cda=0.32,
                custom_swim_min=None, custom_t1t2_min=None):
    """
    Back-calculate per-sport split targets from a finish time goal.

    Physics model (flat course):
      P = (0.5 × rho × CdA × v³  +  Crr × m × g × v) / eta
      CdA  = override via `cda` (default 0.32, triathlon/TT position)
      Crr  = 0.004    (triathlon tires on tarmac)
      rho  = 1.225 kg/m³ (sea level, 15°C)
      eta  = 0.975    (drivetrain efficiency)

    `custom_swim_min` / `custom_t1t2_min` override the model-derived swim time
    and T1+T2 (used by season_plan per-race overrides). Returns a dict with all
    split times, paces, watts and run_pace_ms for use by the race-block builders.
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

    run_pace_ms = (prof["run_km"] * 1000) / (run_min * 60)

    v     = (prof["bike_km"] * 1000) / (bike_min * 60)   # m/s
    watts = (0.5 * 1.225 * cda * v**3 + 0.004 * weight_kg * 9.81 * v) / 0.975
    pct   = watts / ftp

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
