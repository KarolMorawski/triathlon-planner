#!/usr/bin/env python3
"""
strength_core.py — supplementary strength + mobility sessions for the plan.

Deterministic, offline, upload-ready — NO LLM required. Builds Garmin
`strength_training` (sportType 5) and `yoga`/mobility (sportType 7) workout JSON
in the same minimal CREATE shape the swim/bike/run builders use, then schedules
them into an existing swim/bike/run plan (phase-aware: more strength in
base/build, taper toward the race; strength on the lightest days, mobility on
the harder ones as active recovery).

Ported from the garmin-analyzer planner (deterministic variant only).

Garmin schema — confirmed empirically (garmin-analyzer probe, 2026-06-10)
------------------------------------------------------------------------
- Strength  = sportType {5, "strength_training"}. An exercise is an
  ExecutableStepDTO with endCondition {10,"reps"} (or {2,"time"} for held
  moves) carrying `category` + `exerciseName`. Sets = a RepeatGroupDTO
  (stepType {6,"repeat"}, endCondition {7,"iterations"}) wrapping exercise+rest.
- Mobility  = sportType {7, "yoga"}: one time-based block (athlete picks poses).
- weightValue/weightUnit are ALWAYS null in workout TEMPLATES — the implement is
  conveyed by the exercise NAME (BARBELL_*/DUMBBELL_*/GOBLET_*/KETTLEBELL_*),
  the athlete logs the actual load on the watch.

Exercise-name validation
------------------------
Every (category, exerciseName) below is a real pair from Garmin's authoritative
strength taxonomy, verified against the full 47-category / ~1510-exercise enum
set (see garmin-analyzer data/garmin_strength_exercises.json, MIT — Nabil Noh).
We embed only the verified pairs the templates use rather than vendoring the
548 KB file. `build_strength_workout` rejects any pair outside this allowlist,
so a typo never uploads a blank exercise to the watch. To add a NEW exercise,
verify its exact enum against that taxonomy first, then add it to _VALID_PAIRS.
"""

from collections import defaultdict
from datetime import date, timedelta

# ─── SPORT / TARGET CONSTANTS (verified ids) ──────────────────────────────────

SPORT_STRENGTH = {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5}
SPORT_YOGA     = {"sportTypeId": 7, "sportTypeKey": "yoga",              "displayOrder": 8}

_STR_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}

# stepType ids: 1 warmup, 2 cooldown, 3 interval, 5 rest, 6 repeat
# conditionType ids: 1 lap.button, 2 time, 7 iterations, 10 reps

# ─── VERIFIED (category, exerciseName) ALLOWLIST ──────────────────────────────
# Each confirmed present in the authoritative Garmin strength taxonomy.

_VALID_PAIRS = {
    "SQUAT":            {"GOBLET_SQUAT", "AIR_SQUAT"},
    "DEADLIFT":         {"BARBELL_STRAIGHT_LEG_DEADLIFT"},
    "PUSH_UP":          {"PUSH_UP"},
    "ROW":              {"BENT_OVER_ROW_WITH_BARBELL"},
    "PLANK":            {"PLANK", "SIDE_PLANK"},
    "BANDED_EXERCISES": {"CLAM_SHELLS"},
    "PULL_UP":          {"PULL_UP"},
    "HIP_RAISE":        {"BARBELL_HIP_THRUST_ON_FLOOR"},
    "LUNGE":            {"REVERSE_DUMBBELL_BOX_LUNGE"},
}


class UnknownExerciseError(ValueError):
    """Raised when a (category, exerciseName) pair isn't in the allowlist."""


def is_valid_strength_pair(category, exercise_name):
    return exercise_name in _VALID_PAIRS.get(category, frozenset())


# ─── EXERCISE / SPEC HELPERS (plain dicts) ────────────────────────────────────

def ex(category, exercise_name, reps=None, seconds=None, sets=1, rest_s=60):
    """One prescribed move. `reps` XOR `seconds` picks reps-count vs held-time."""
    return {"category": category, "exercise_name": exercise_name,
            "reps": reps, "seconds": seconds, "sets": sets, "rest_s": rest_s}


# ─── STEP BUILDERS (minimal CREATE shape) ─────────────────────────────────────

def _exec_step(order, step_type_id, step_type_key, cond_id, cond_key, value,
               category=None, exercise_name=None):
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": step_type_id, "stepTypeKey": step_type_key,
                     "displayOrder": step_type_id},
        "childStepId": None,
        "description": None,
        "endCondition": {"conditionTypeId": cond_id, "conditionTypeKey": cond_key,
                         "displayOrder": cond_id, "displayable": True},
        "endConditionValue": float(value),
        "targetType": _STR_NO_TARGET,
        "targetValueOne": None,
        "targetValueTwo": None,
        "targetValueUnit": None,
        "category": category,
        "exerciseName": exercise_name,
        "weightValue": None,
        "weightUnit": None,
    }


def _warmup(order):  return _exec_step(order, 1, "warmup",   1, "lap.button", 1)
def _cooldown(order): return _exec_step(order, 2, "cooldown", 1, "lap.button", 1)
def _rest(order, seconds): return _exec_step(order, 5, "rest", 2, "time", seconds)


def _exercise_step(order, e):
    # Treat non-positive reps/seconds as "unspecified" → sane default, so a stray
    # 0 never uploads a broken 0-rep / 0-second step to the watch.
    if e["seconds"] is not None and e["seconds"] > 0:
        cond_id, cond_key, value = 2, "time", float(e["seconds"])
    else:
        reps = e["reps"] if (e["reps"] is not None and e["reps"] > 0) else 10
        cond_id, cond_key, value = 10, "reps", float(reps)
    return _exec_step(order, 3, "interval", cond_id, cond_key, value,
                      category=e["category"], exercise_name=e["exercise_name"])


def _repeat_group(order, iterations, child_steps):
    return {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
        "numberOfIterations": iterations,
        "workoutSteps": child_steps,
        "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations",
                         "displayOrder": 7, "displayable": False},
        "endConditionValue": float(iterations),
        "skipLastRestStep": False,
        "smartRepeat": False,
    }


def _estimate_duration(exercises):
    """Rough: reps→~3s each, timed→held seconds, plus rest between sets."""
    total = 0
    for e in exercises:
        per_set = e["seconds"] if e["seconds"] is not None else (e["reps"] or 10) * 3
        total += e["sets"] * per_set + max(0, e["sets"] - 1) * e["rest_s"]
    return int(total)


def build_strength_workout(name, exercises, description=None):
    """Build an uploadable Garmin strength_training workout.

    Raises UnknownExerciseError if any (category, exerciseName) is outside the
    verified allowlist."""
    for e in exercises:
        if not is_valid_strength_pair(e["category"], e["exercise_name"]):
            raise UnknownExerciseError(
                f"{e['category']}/{e['exercise_name']} is not a valid strength "
                f"(category, exerciseName) pair")
    steps, order = [], 1
    steps.append(_warmup(order)); order += 1
    for e in exercises:
        if e["sets"] > 1:
            child = [_exercise_step(order + 1, e), _rest(order + 2, e["rest_s"])]
            steps.append(_repeat_group(order, e["sets"], child)); order += 3
        else:
            steps.append(_exercise_step(order, e)); order += 1
    steps.append(_cooldown(order))
    return {
        "sportType": SPORT_STRENGTH,
        "workoutName": name,
        "description": description or None,
        "workoutSegments": [{"segmentOrder": 1, "sportType": SPORT_STRENGTH,
                             "workoutSteps": steps}],
        "estimatedDurationInSecs": _estimate_duration(exercises),
        "estimatedDistanceInMeters": None,
        "avgTrainingSpeed": None,
        "workoutProvider": None,
        "workoutSourceId": None,
        "isAtp": False,
    }


def build_mobility_workout(name, minutes, description=None):
    """Build a Garmin yoga/mobility workout as a single timed block (no poses —
    the athlete runs their own stretching routine against a countdown)."""
    step = _exec_step(1, 3, "interval", 2, "time", minutes * 60)
    return {
        "sportType": SPORT_YOGA,
        "workoutName": name,
        "description": description or None,
        "workoutSegments": [{"segmentOrder": 1, "sportType": SPORT_YOGA,
                             "workoutSteps": [step]}],
        "estimatedDurationInSecs": minutes * 60,
        "estimatedDistanceInMeters": None,
        "avgTrainingSpeed": None,
        "workoutProvider": None,
        "workoutSourceId": None,
        "isAtp": False,
    }


# ─── PERIODISATION ────────────────────────────────────────────────────────────

BASE, BUILD, PEAK, TAPER = "base", "build", "peak", "taper"


def phase_for(weeks_to_race):
    """Map weeks-until-race to a periodisation phase."""
    if weeks_to_race > 8: return BASE
    if weeks_to_race > 4: return BUILD
    if weeks_to_race > 2: return PEAK
    return TAPER


STRENGTH_PER_WEEK = {BASE: 2, BUILD: 2, PEAK: 1, TAPER: 1}
MOBILITY_PER_WEEK = {BASE: 2, BUILD: 2, PEAK: 3, TAPER: 2}
MOBILITY_MINUTES  = {BASE: 20, BUILD: 20, PEAK: 20, TAPER: 15}

# Deterministic per-phase strength templates. Planks are time-based (held).
_PHASE_TEMPLATES = {
    # Base: foundational full-body, moderate volume.
    BASE: [
        ex("SQUAT", "GOBLET_SQUAT", reps=12, sets=3, rest_s=75),
        ex("DEADLIFT", "BARBELL_STRAIGHT_LEG_DEADLIFT", reps=10, sets=3, rest_s=90),
        ex("PUSH_UP", "PUSH_UP", reps=12, sets=3, rest_s=60),
        ex("ROW", "BENT_OVER_ROW_WITH_BARBELL", reps=12, sets=3, rest_s=75),
        ex("PLANK", "PLANK", seconds=45, sets=3, rest_s=45),
        ex("BANDED_EXERCISES", "CLAM_SHELLS", reps=15, sets=2, rest_s=45),
    ],
    # Build: strength bias, heavier compounds, slightly lower reps.
    BUILD: [
        ex("SQUAT", "GOBLET_SQUAT", reps=8, sets=4, rest_s=90),
        ex("DEADLIFT", "BARBELL_STRAIGHT_LEG_DEADLIFT", reps=8, sets=4, rest_s=120),
        ex("PULL_UP", "PULL_UP", reps=8, sets=3, rest_s=90),
        ex("HIP_RAISE", "BARBELL_HIP_THRUST_ON_FLOOR", reps=10, sets=3, rest_s=90),
        ex("LUNGE", "REVERSE_DUMBBELL_BOX_LUNGE", reps=10, sets=3, rest_s=75),
        ex("PLANK", "SIDE_PLANK", seconds=40, sets=2, rest_s=45),
    ],
    # Peak: maintenance — fewer sets, keep the patterns sharp.
    PEAK: [
        ex("SQUAT", "AIR_SQUAT", reps=15, sets=2, rest_s=60),
        ex("LUNGE", "REVERSE_DUMBBELL_BOX_LUNGE", reps=10, sets=2, rest_s=60),
        ex("PUSH_UP", "PUSH_UP", reps=12, sets=2, rest_s=60),
        ex("PLANK", "PLANK", seconds=45, sets=2, rest_s=45),
    ],
    # Taper: minimal activation, keep it light into race week.
    TAPER: [
        ex("SQUAT", "AIR_SQUAT", reps=12, sets=1),
        ex("BANDED_EXERCISES", "CLAM_SHELLS", reps=15, sets=1),
        ex("PLANK", "PLANK", seconds=30, sets=1),
    ],
}


def strength_exercises_for_phase(phase):
    """The strength exercise list for a phase (copy, so callers can't mutate)."""
    return [dict(e) for e in _PHASE_TEMPLATES[phase]]


# ─── SCHEDULING ───────────────────────────────────────────────────────────────

def _iter_week_starts(start, end):
    """Yield Monday of each ISO week overlapping [start, end]."""
    cur = start - timedelta(days=start.weekday())
    while cur <= end:
        yield cur
        cur += timedelta(days=7)


def _pick_days(week_days, load, n, prefer_low, blocked):
    """Pick `n` days from a week ordered by existing load. `prefer_low` picks the
    lightest days (strength); otherwise heaviest (mobility as active recovery).
    Skips `blocked`. Stable tie-break by date."""
    candidates = [d for d in week_days if d not in blocked]
    candidates.sort(key=lambda d: (load.get(d, 0), d.toordinal()), reverse=not prefer_low)
    return candidates[:n]


def schedule_supplementary(existing, race_date):
    """Decide (date, phase, kind) slots for strength/mobility sessions.

    `existing` is the plan's current (workout_json, iso_date) list. `kind` is
    "strength" or "mobility". Pure scheduling — no workout JSON built here."""
    dates = sorted({date.fromisoformat(d) for _, d in existing})
    if not dates:
        return []
    plan_start, plan_end = dates[0], dates[-1]

    load = defaultdict(int)
    for _, d in existing:
        load[date.fromisoformat(d)] += 1

    slots = []
    for monday in _iter_week_starts(plan_start, plan_end):
        week_days = [monday + timedelta(days=i) for i in range(7)]
        # Clamp to the plan window AND strictly before race day — never schedule
        # supplementary work on or after the race.
        week_days = [d for d in week_days if plan_start <= d <= plan_end and d < race_date]
        if not week_days:
            continue
        weeks_to_race = (race_date - monday).days / 7.0
        phase = phase_for(weeks_to_race)

        # Strength on the lightest days; never on race day or the 2 days before.
        taper_block = {race_date, race_date - timedelta(days=1), race_date - timedelta(days=2)}
        str_days = _pick_days(week_days, load, STRENGTH_PER_WEEK[phase],
                              prefer_low=True, blocked=taper_block)
        for day in str_days:
            slots.append((day, phase, "strength"))

        # Mobility on the heaviest days (active recovery), avoiding strength days.
        mob_days = _pick_days(week_days, load, MOBILITY_PER_WEEK[phase],
                              prefer_low=False, blocked=set(str_days) | {race_date})
        for day in mob_days:
            slots.append((day, phase, "mobility"))

    return sorted(slots, key=lambda s: (s[0].toordinal(), s[2]))


def augment_plan(existing, race_date, name_prefix=None,
                 strength_desc=None, mobility_name="Mobility", strength_name="Strength"):
    """Return NEW (workout_json, iso_date) entries to append to a plan:
    structured strength + timed mobility sessions, scheduled by phase.

    `name_prefix` (the race prefix, e.g. "WARSAW") prefixes each workout name to
    match the endurance sessions' `{PREFIX}-T{wk:02d} ...` convention — so they
    group with the plan, get cleaned up by the prefix-keyed Garmin wipe, and read
    consistently. Omit it to keep the bare name."""
    dates = sorted({date.fromisoformat(d) for _, d in existing})
    plan_start = dates[0] if dates else race_date

    out = []
    for d, phase, kind in schedule_supplementary(existing, race_date):
        if kind == "strength":
            wkt = build_strength_workout(f"{strength_name} · {phase}",
                                         strength_exercises_for_phase(phase),
                                         description=strength_desc)
        else:
            minutes = MOBILITY_MINUTES[phase]
            wkt = build_mobility_workout(f"{mobility_name} · {minutes} min", minutes=minutes)
        if name_prefix:
            wk = max(1, (d - plan_start).days // 7 + 1)
            wkt["workoutName"] = f"{name_prefix}-T{wk:02d} {wkt['workoutName']}"
        out.append((wkt, d.isoformat()))
    return out
