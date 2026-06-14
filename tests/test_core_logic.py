"""Pure-logic regression tests — no network, no Garmin login.

These guard the deterministic core that the plan generators share. They exist
precisely because duplicated copies of PROFILES / calc_splits had already
DRIFTED between season_plan.py and generate_plan.py before consolidation; a
single source of truth is only safe if something keeps it single.

Run:  pip install pytest && pytest -q
"""

from datetime import date, timedelta

import pytest

import triathlon_core as core
import strength_core as st


# ─── single source of truth (the anti-drift guard) ───────────────────────────

def test_profiles_is_one_object_across_modules():
    import season_plan
    import season_plan_en
    import generate_plan
    import generate_plan_en
    assert season_plan.PROFILES is core.PROFILES
    assert season_plan_en.PROFILES is core.PROFILES
    assert generate_plan.PROFILES is core.PROFILES
    assert generate_plan_en.PROFILES is core.PROFILES


def test_profiles_use_canonical_race_bike_pct_key():
    # The long-standing bug: generate_plan called this key `race_pace_pct`.
    for dist, prof in core.PROFILES.items():
        assert "race_bike_pct" in prof, f"{dist} missing race_bike_pct"
        assert "race_pace_pct" not in prof, f"{dist} still uses legacy race_pace_pct"


def test_profiles_and_split_ratios_cover_same_distances_minus_quarter():
    # SPLIT_RATIOS intentionally has no 'quarter' (it falls back elsewhere);
    # every SPLIT_RATIOS distance must exist in PROFILES.
    assert set(core.SPLIT_RATIOS).issubset(set(core.PROFILES))


@pytest.mark.parametrize("dist", list(core.PROFILES))
def test_profile_fields_present_and_sane(dist):
    p = core.PROFILES[dist]
    for f in ("label", "weeks", "swim_m", "bike_km", "run_km", "race_bike_pct"):
        assert f in p
    assert p["swim_m"] > 0 and p["bike_km"] > 0 and p["run_km"] > 0
    assert 0.5 < p["race_bike_pct"] <= 0.95
    assert 1 <= p["weeks"] <= 24


# ─── pace / time helpers ──────────────────────────────────────────────────────

@pytest.mark.parametrize("pace", ["3:30", "4:00", "5:20", "6:05", "7:59"])
def test_pace_round_trip(pace):
    assert core.ms_to_pace(core.pace_to_ms(pace)) == pace


def test_ms_to_pace_rounds_seconds_without_60():
    # 59.6 s/km must roll to next minute, never render ':60'
    assert ":60" not in core.ms_to_pace(1000.0 / (3 * 60 + 59.6))


@pytest.mark.parametrize("s,minutes", [
    ("5:00:00", 300.0), ("1:30", 90.0), ("0:45:30", 45.5),
])
def test_parse_hms(s, minutes):
    assert core._parse_hms(s) == pytest.approx(minutes)


def test_parse_hms_rejects_garbage():
    with pytest.raises(ValueError):
        core._parse_hms("nonsense")


def test_fmt_hm():
    assert core._fmt_hm(125) == "2:05"


# ─── calc_splits (physics model) ──────────────────────────────────────────────

def test_calc_splits_known_70_3_five_hours():
    s = core.calc_splits("70.3", "5:00:00", ftp=255, weight_kg=80, cda=0.32)
    # Stable reference values for this input (flat-course model).
    assert s["bike_watts"] == pytest.approx(218, abs=2)
    assert s["bike_pct_ftp"] == pytest.approx(0.86, abs=0.02)
    assert s["run_pace_str"] == "4:57"
    assert s["swim_min"] + s["bike_min"] + s["run_min"] + s["t1t2_min"] == pytest.approx(300.0)


def test_calc_splits_custom_swim_min_override():
    s = core.calc_splits("70.3", "5:00:00", 255, 80, custom_swim_min=40)
    assert s["swim_min"] == 40
    assert s["swim_min"] + s["bike_min"] + s["run_min"] + s["t1t2_min"] == pytest.approx(300.0)


def test_calc_splits_rejects_bad_ftp():
    with pytest.raises(ValueError):
        core.calc_splits("70.3", "5:00:00", ftp=0)


def test_calc_splits_rejects_impossible_time():
    with pytest.raises(ValueError):
        core.calc_splits("sprint", "0:02", ftp=255)  # shorter than T1+T2


# ─── strength_core: content validity + schedule invariants ────────────────────

def test_all_template_pairs_are_valid():
    for phase in (st.BASE, st.BUILD, st.PEAK, st.TAPER):
        for e in st.strength_exercises_for_phase(phase):
            assert st.is_valid_strength_pair(e["category"], e["exercise_name"]), \
                f"{e['category']}/{e['exercise_name']} not in allowlist"


def test_build_strength_workout_structure():
    w = st.build_strength_workout("X", st.strength_exercises_for_phase(st.BASE))
    assert w["sportType"]["sportTypeId"] == 5
    steps = w["workoutSegments"][0]["workoutSteps"]
    assert steps[0]["stepType"]["stepTypeKey"] == "warmup"
    assert steps[-1]["stepType"]["stepTypeKey"] == "cooldown"
    assert any(s["type"] == "RepeatGroupDTO" for s in steps)
    assert w["estimatedDurationInSecs"] > 0


def test_build_strength_rejects_unknown_pair():
    with pytest.raises(st.UnknownExerciseError):
        st.build_strength_workout("X", [st.ex("SQUAT", "NOT_A_REAL_LIFT", reps=5)])


def test_mobility_workout_is_yoga_timed_block():
    w = st.build_mobility_workout("Mob", minutes=20)
    assert w["sportType"]["sportTypeId"] == 7
    assert w["estimatedDurationInSecs"] == 20 * 60


def _synthetic_plan(weeks=10):
    race = date(2026, 9, 1)
    start = race - timedelta(weeks=weeks)
    start -= timedelta(days=start.weekday())
    existing, sports, d = [], ["swim", "bike", "run", "bike"], start
    while d < race:
        wk = d - timedelta(days=d.weekday())
        for i, off in enumerate([0, 1, 2, 5]):
            day = wk + timedelta(days=off)
            if day < race:
                existing.append(({"sportType": {"sportTypeKey": sports[i]}}, day.isoformat()))
        d += timedelta(days=7)
    return existing, race


def test_schedule_invariants():
    existing, race = _synthetic_plan()
    aug = st.augment_plan(existing, race, name_prefix="WARSAW")
    strength = [date.fromisoformat(dd) for w, dd in aug
                if w["sportType"]["sportTypeKey"] == "strength_training"]
    mobility = [date.fromisoformat(dd) for w, dd in aug
                if w["sportType"]["sportTypeKey"] == "yoga"]
    assert strength and mobility
    # strength never within 2 days of race; nothing on/after race day
    assert all(s <= race - timedelta(days=3) for s in strength)
    assert all(d < race for d in strength + mobility)
    # no day is both a strength and a mobility day
    assert not (set(strength) & set(mobility))
    # names carry the plan prefix so --reset cleans them up
    assert all(w["workoutName"].startswith("WARSAW-T") for w, _ in aug)


def test_phase_mapping():
    assert st.phase_for(10) == st.BASE
    assert st.phase_for(6) == st.BUILD
    assert st.phase_for(3) == st.PEAK
    assert st.phase_for(1) == st.TAPER
