#!/usr/bin/env python3
"""
triathlon_core.py — shared utilities for the triathlon training planner suite.

Exports
-------
Constants:       STATE_DIR, TOKEN_FILE
Validation:      validate_prefix_pl, validate_prefix_en
State I/O:       load_state_pl, load_state_en
Garmin login:    login, login_pl, login_en
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
import os
import re
import sys

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
