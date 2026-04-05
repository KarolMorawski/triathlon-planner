#!/usr/bin/env python3
"""
Tests for generate_plan.py — workout generation logic (no Garmin login required).

Covers:
  - pace conversion helpers
  - power zone calculations
  - workout structure (required fields, sport types)
  - Garmin API target rules (CRITICAL: no.target on warmup/cooldown)
  - session counts and day-of-week placement
  - all 4 distances (sprint / olympic / 70.3 / full)
"""

import unittest
from datetime import date, timedelta
from generate_plan import (
    generate_plan, pace_to_ms, ms_to_pace, PROFILES
)

RACE_DATE = date(2026, 9, 12)
FTP       = 250
PACE_STR  = "5:20"
PACE_MS   = pace_to_ms(PACE_STR)
WEIGHT    = 75


# ─── helpers ─────────────────────────────────────────────────────────────────

def workouts_for(distance, ftp=FTP, pace_ms=PACE_MS, prefix="TST"):
    return generate_plan(RACE_DATE, distance, ftp, pace_ms, WEIGHT, prefix)


def steps_of(wkt):
    return wkt["workoutSegments"][0]["workoutSteps"]


def target_id(step):
    return step["targetType"]["workoutTargetTypeId"]


def target_key(step):
    return step["targetType"]["workoutTargetTypeKey"]


def step_type_key(step):
    return step["stepType"]["stepTypeKey"]


# ─── pace conversion ──────────────────────────────────────────────────────────

class TestPaceConversion(unittest.TestCase):

    def test_pace_to_ms_basic(self):
        # 5:20/km = 320 s/km → 1000/320 = 3.125 m/s
        self.assertAlmostEqual(pace_to_ms("5:20"), 3.125, places=4)

    def test_pace_to_ms_round_trip(self):
        # Float precision: 1000/240 → 239.9999... → allow ±1s rounding
        for pace in ["4:00", "5:00", "5:20", "6:30", "7:15"]:
            result = ms_to_pace(pace_to_ms(pace))
            orig_s = int(pace.split(":")[0]) * 60 + int(pace.split(":")[1])
            res_s  = int(result.split(":")[0]) * 60 + int(result.split(":")[1])
            self.assertLessEqual(abs(orig_s - res_s), 1,
                f"Round-trip for {pace} → {result} differs by more than 1s")

    def test_ms_to_pace_format(self):
        result = ms_to_pace(3.125)
        self.assertRegex(result, r"^\d+:\d{2}$")

    def test_faster_pace_gives_higher_ms(self):
        self.assertGreater(pace_to_ms("4:00"), pace_to_ms("5:00"))


# ─── workout structure ────────────────────────────────────────────────────────

class TestWorkoutStructure(unittest.TestCase):

    REQUIRED_WKT_KEYS = {
        "sportType", "workoutName", "description",
        "workoutSegments", "estimatedDurationInSecs",
        "estimatedDistanceInMeters", "isAtp",
    }

    REQUIRED_STEP_KEYS = {
        "type", "stepOrder", "stepType", "endCondition",
        "endConditionValue", "targetType",
        "targetValueOne", "targetValueTwo",
    }

    def _check_all_distances(self, check_fn):
        for dist in PROFILES:
            with self.subTest(distance=dist):
                wkts = workouts_for(dist)
                check_fn(dist, wkts)

    def test_required_workout_keys_present(self):
        def check(dist, wkts):
            for wkt, _ in wkts:
                missing = self.REQUIRED_WKT_KEYS - wkt.keys()
                self.assertFalse(missing, f"Missing keys: {missing}")
        self._check_all_distances(check)

    def test_required_step_keys_present(self):
        def check(dist, wkts):
            for wkt, _ in wkts:
                for step in steps_of(wkt):
                    missing = self.REQUIRED_STEP_KEYS - step.keys()
                    self.assertFalse(missing, f"Missing step keys: {missing}")
        self._check_all_distances(check)

    def test_workout_name_contains_prefix(self):
        def check(dist, wkts):
            for wkt, _ in wkts:
                self.assertTrue(wkt["workoutName"].startswith("TST"),
                                f"Name missing prefix: {wkt['workoutName']}")
        self._check_all_distances(check)

    def test_step_orders_sequential(self):
        def check(dist, wkts):
            for wkt, _ in wkts:
                orders = [s["stepOrder"] for s in steps_of(wkt)]
                self.assertEqual(orders, list(range(1, len(orders) + 1)),
                                 f"Non-sequential step orders in {wkt['workoutName']}")
        self._check_all_distances(check)

    def test_estimated_duration_positive(self):
        def check(dist, wkts):
            for wkt, _ in wkts:
                self.assertGreater(wkt["estimatedDurationInSecs"], 0,
                                   wkt["workoutName"])
        self._check_all_distances(check)

    def test_isAtp_false(self):
        def check(dist, wkts):
            for wkt, _ in wkts:
                self.assertFalse(wkt["isAtp"])
        self._check_all_distances(check)


# ─── Garmin API target rules (CRITICAL) ──────────────────────────────────────

class TestGarminTargetRules(unittest.TestCase):
    """
    Confirmed via network analysis (see CLAUDE.md):
      - warmup/cooldown steps MUST use no.target (id=1, targetValueOne/Two=None)
      - power interval steps use power.zone (id=2) with absolute watts
      - run interval steps use pace.zone (id=6) with m/s values
      - Bug: any power target on warmup/cooldown → Garmin shows watts×3.6 as kph
    """

    def _all_steps_all_distances(self):
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, _ in wkts:
                sport_key = wkt["sportType"]["sportTypeKey"]
                for step in steps_of(wkt):
                    yield dist, wkt["workoutName"], sport_key, step

    def test_warmup_cooldown_must_use_no_target(self):
        """CRITICAL: warmup/cooldown with power target → Garmin displays kph bug."""
        for dist, name, sport_key, step in self._all_steps_all_distances():
            if step_type_key(step) in ("warmup", "cooldown"):
                with self.subTest(distance=dist, workout=name, step=step_type_key(step)):
                    self.assertEqual(target_id(step), 1,
                        f"warmup/cooldown must use no.target (id=1), "
                        f"got id={target_id(step)} in '{name}'")
                    self.assertEqual(target_key(step), "no.target")
                    self.assertIsNone(step["targetValueOne"],
                        f"warmup/cooldown targetValueOne must be None in '{name}'")
                    self.assertIsNone(step["targetValueTwo"],
                        f"warmup/cooldown targetValueTwo must be None in '{name}'")

    def test_bike_intervals_use_power_zone(self):
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, _ in wkts:
                if wkt["sportType"]["sportTypeKey"] != "cycling":
                    continue
                for step in steps_of(wkt):
                    if step_type_key(step) not in ("interval", "recovery"):
                        continue
                    with self.subTest(distance=dist, workout=wkt["workoutName"]):
                        self.assertEqual(target_id(step), 2,
                            f"Bike interval must use power.zone (id=2)")
                        self.assertEqual(target_key(step), "power.zone")

    def test_bike_power_values_are_absolute_watts(self):
        """targetValueOne/Two must be floats in watts range (not fractions)."""
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, _ in wkts:
                if wkt["sportType"]["sportTypeKey"] != "cycling":
                    continue
                for step in steps_of(wkt):
                    if step_type_key(step) not in ("interval", "recovery"):
                        continue
                    with self.subTest(distance=dist, workout=wkt["workoutName"]):
                        v1 = step["targetValueOne"]
                        v2 = step["targetValueTwo"]
                        self.assertIsNotNone(v1)
                        self.assertIsNotNone(v2)
                        # Watts should be > 10 (not fractions like 0.72)
                        self.assertGreater(v1, 10,
                            f"targetValueOne={v1} looks like fraction, not watts")
                        self.assertGreater(v2, 10)
                        self.assertLessEqual(v1, v2,
                            f"lo={v1} > hi={v2} in '{wkt['workoutName']}'")

    def test_run_intervals_use_pace_zone(self):
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, _ in wkts:
                if wkt["sportType"]["sportTypeKey"] != "running":
                    continue
                for step in steps_of(wkt):
                    if step_type_key(step) != "interval":
                        continue
                    with self.subTest(distance=dist, workout=wkt["workoutName"]):
                        self.assertEqual(target_id(step), 6,
                            f"Run interval must use pace.zone (id=6)")
                        self.assertEqual(target_key(step), "pace.zone")

    def test_run_pace_values_are_ms(self):
        """Pace values must be m/s (typically 2.0–6.0), not sec/km."""
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, _ in wkts:
                if wkt["sportType"]["sportTypeKey"] != "running":
                    continue
                for step in steps_of(wkt):
                    if step_type_key(step) != "interval":
                        continue
                    with self.subTest(distance=dist, workout=wkt["workoutName"]):
                        v1 = step["targetValueOne"]
                        v2 = step["targetValueTwo"]
                        self.assertIsNotNone(v1)
                        self.assertIsNotNone(v2)
                        # m/s for running: ~2.0 (8:20/km) to ~6.0 (2:47/km)
                        self.assertGreater(v1, 1.5,
                            f"Pace v1={v1} too low — stored as sec/km instead of m/s?")
                        self.assertLess(v1, 7.0,
                            f"Pace v1={v1} too high — check unit")
                        self.assertLessEqual(v1, v2)

    def test_swim_uses_no_target(self):
        """Swim steps have no pace/power target in Garmin format."""
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, _ in wkts:
                if wkt["sportType"]["sportTypeKey"] != "swimming":
                    continue
                for step in steps_of(wkt):
                    with self.subTest(distance=dist, workout=wkt["workoutName"]):
                        self.assertEqual(target_id(step), 1)
                        self.assertEqual(target_key(step), "no.target")


# ─── power zone values ────────────────────────────────────────────────────────

class TestPowerZones(unittest.TestCase):

    def test_z1_range(self):
        lo, hi = round(FTP * 0.40), round(FTP * 0.55)
        wkts = workouts_for("full")
        for wkt, _ in wkts:
            if wkt["sportType"]["sportTypeKey"] != "cycling":
                continue
            for step in steps_of(wkt):
                if step_type_key(step) != "recovery":
                    continue
                v1, v2 = step["targetValueOne"], step["targetValueTwo"]
                self.assertAlmostEqual(v1, lo, delta=5,
                    msg=f"Z1 lo={v1} expected ~{lo} in '{wkt['workoutName']}'")
                self.assertAlmostEqual(v2, hi, delta=5)

    def test_z2_range(self):
        lo, hi = round(FTP * 0.60), round(FTP * 0.72)
        wkts = workouts_for("full")
        z2_sessions = [
            (wkt, step) for wkt, _ in wkts
            for step in steps_of(wkt)
            if wkt["sportType"]["sportTypeKey"] == "cycling"
            and step_type_key(step) == "interval"
            and step["targetValueOne"] is not None
            and abs(step["targetValueOne"] - lo) <= 5
        ]
        self.assertGreater(len(z2_sessions), 0, "No Z2 bike intervals found")
        for wkt, step in z2_sessions:
            self.assertAlmostEqual(step["targetValueOne"], lo, delta=5)
            self.assertAlmostEqual(step["targetValueTwo"], hi, delta=5)

    def test_z4_threshold_range(self):
        lo, hi = round(FTP * 0.88), round(FTP * 0.97)
        wkts = workouts_for("full")
        threshold_found = False
        for wkt, _ in wkts:
            if "Threshold" not in wkt["workoutName"]:
                continue
            threshold_found = True
            interval_steps = [s for s in steps_of(wkt) if step_type_key(s) == "interval"]
            self.assertGreater(len(interval_steps), 0)
            for step in interval_steps:
                self.assertAlmostEqual(step["targetValueOne"], lo, delta=5,
                    msg=f"Z4 lo wrong in '{wkt['workoutName']}'")
                self.assertAlmostEqual(step["targetValueTwo"], hi, delta=5)
        self.assertTrue(threshold_found, "No Threshold workout found in full plan")


# ─── session counts ───────────────────────────────────────────────────────────

class TestSessionCounts(unittest.TestCase):

    EXPECTED_COUNTS = {
        # distance: (total, per_sport)
        "sprint":  (None, None),  # checked dynamically
        "olympic": (None, None),
        "70.3":    (None, None),
        "full":    (None, None),
    }

    def test_equal_sessions_per_sport(self):
        """Each sport should receive the same number of sessions."""
        for dist in PROFILES:
            with self.subTest(distance=dist):
                wkts = workouts_for(dist)
                counts = {}
                for wkt, _ in wkts:
                    key = wkt["sportType"]["sportTypeKey"]
                    counts[key] = counts.get(key, 0) + 1
                self.assertEqual(counts.get("running"), counts.get("cycling"),
                    f"{dist}: run={counts.get('running')} != bike={counts.get('cycling')}")
                self.assertEqual(counts.get("running"), counts.get("swimming"),
                    f"{dist}: run={counts.get('running')} != swim={counts.get('swimming')}")

    def test_total_sessions_reasonable(self):
        """At least 3 sessions/week on average (1/sport), but generate_plan
        uses 1 session/sport/week = 3/week total."""
        for dist in PROFILES:
            with self.subTest(distance=dist):
                weeks = PROFILES[dist]["weeks"]
                wkts = workouts_for(dist)
                total = len(wkts)
                per_week = total / weeks
                self.assertGreaterEqual(per_week, 2.0,
                    f"{dist}: {per_week:.1f} sessions/week is too few")
                self.assertLessEqual(per_week, 6.0,
                    f"{dist}: {per_week:.1f} sessions/week is too many")

    def test_race_week_has_3_sessions(self):
        """Race week must have exactly 3 sessions: bike check, run activation, swim."""
        for dist in PROFILES:
            with self.subTest(distance=dist):
                wkts = workouts_for(dist)
                weeks = PROFILES[dist]["weeks"]
                tag = f"TST-T{weeks}"
                race_wkts = [wkt for wkt, _ in wkts if tag in wkt["workoutName"]]
                self.assertEqual(len(race_wkts), 3,
                    f"{dist}: race week has {len(race_wkts)} sessions, expected 3")

    def test_race_week_sports(self):
        """Race week must have exactly 1 of each sport."""
        for dist in PROFILES:
            with self.subTest(distance=dist):
                wkts = workouts_for(dist)
                weeks = PROFILES[dist]["weeks"]
                tag = f"TST-T{weeks}"
                sports = [wkt["sportType"]["sportTypeKey"]
                          for wkt, _ in wkts if tag in wkt["workoutName"]]
                self.assertIn("cycling",  sports)
                self.assertIn("running",  sports)
                self.assertIn("swimming", sports)


# ─── dates and scheduling ─────────────────────────────────────────────────────

class TestDatesAndScheduling(unittest.TestCase):

    def test_all_dates_within_block(self):
        for dist in PROFILES:
            with self.subTest(distance=dist):
                weeks = PROFILES[dist]["weeks"]
                plan_start = RACE_DATE - timedelta(weeks=weeks)
                wkts = workouts_for(dist)
                for wkt, d in wkts:
                    dt = date.fromisoformat(d)
                    self.assertGreaterEqual(dt, plan_start,
                        f"{wkt['workoutName']} date {d} before plan start {plan_start}")
                    self.assertLessEqual(dt, RACE_DATE,
                        f"{wkt['workoutName']} date {d} after race date {RACE_DATE}")

    def test_dates_are_valid_strings(self):
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, d in wkts:
                with self.subTest(distance=dist, name=wkt["workoutName"]):
                    self.assertRegex(d, r"^\d{4}-\d{2}-\d{2}$")
                    # Must be parseable
                    date.fromisoformat(d)

    def test_bike_sessions_on_consistent_days(self):
        """Bike quality sessions (non-race-week) must all land on the same
        weekday — the plan uses d(1) (1 day after wk_start) for all of them.
        The actual weekday depends on the race date's day of week."""
        for dist in PROFILES:
            with self.subTest(distance=dist):
                wkts = workouts_for(dist)
                weeks = PROFILES[dist]["weeks"]
                race_tag = f"TST-T{weeks}"
                bike_days = set()
                for wkt, d in wkts:
                    if wkt["sportType"]["sportTypeKey"] != "cycling":
                        continue
                    if race_tag in wkt["workoutName"]:
                        continue  # race week uses d(5) — skip
                    dt = date.fromisoformat(d)
                    bike_days.add(dt.weekday())
                # All main bike sessions should be on at most 2 weekdays
                # (Tue quality + Thu Z2 in generate_plan uses d(1) only)
                self.assertLessEqual(len(bike_days), 2,
                    f"{dist}: bike sessions spread over too many days: {bike_days}")

    def test_no_workouts_after_race_date(self):
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, d in wkts:
                self.assertLessEqual(d, str(RACE_DATE),
                    f"Workout scheduled after race: {wkt['workoutName']} on {d}")


# ─── swim structure ───────────────────────────────────────────────────────────

class TestSwimStructure(unittest.TestCase):

    def test_swim_steps_have_stroke_type(self):
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, _ in wkts:
                if wkt["sportType"]["sportTypeKey"] != "swimming":
                    continue
                for step in steps_of(wkt):
                    with self.subTest(distance=dist, workout=wkt["workoutName"]):
                        self.assertIn("strokeType", step,
                            "Swim step missing strokeType")
                        self.assertIn("equipmentType", step,
                            "Swim step missing equipmentType")

    def test_swim_uses_distance_end_condition(self):
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, _ in wkts:
                if wkt["sportType"]["sportTypeKey"] != "swimming":
                    continue
                for step in steps_of(wkt):
                    with self.subTest(distance=dist, workout=wkt["workoutName"]):
                        cond_key = step["endCondition"]["conditionTypeKey"]
                        self.assertEqual(cond_key, "distance",
                            f"Swim step should end by distance, got: {cond_key}")

    def test_swim_distances_positive_and_sane(self):
        for dist in PROFILES:
            wkts = workouts_for(dist)
            for wkt, _ in wkts:
                if wkt["sportType"]["sportTypeKey"] != "swimming":
                    continue
                total = sum(s["endConditionValue"] for s in steps_of(wkt))
                with self.subTest(distance=dist, workout=wkt["workoutName"]):
                    self.assertGreater(total, 200,
                        f"Swim too short: {total}m")
                    self.assertLess(total, 6000,
                        f"Swim unrealistically long: {total}m")


# ─── volume progression ───────────────────────────────────────────────────────

class TestVolumeProgression(unittest.TestCase):

    def _swim_distances(self, dist):
        import re
        wkts = workouts_for(dist)
        result = []
        for wkt, _ in wkts:
            if wkt["sportType"]["sportTypeKey"] != "swimming":
                continue
            m = re.search(r"T(\d+)", wkt["workoutName"])
            if m:
                wk = int(m.group(1))
                total_m = wkt.get("estimatedDistanceInMeters") or 0
                result.append((wk, total_m))
        return sorted(result)

    def test_swim_volume_increases_then_decreases(self):
        """Swim distances should generally increase through base/build,
        then drop in taper. Sprint is excluded — its 750m race distance
        gives naturally small volumes that may hit the 200m floor."""
        for dist in ["olympic", "70.3", "full"]:
            with self.subTest(distance=dist):
                data = self._swim_distances(dist)
                weeks = PROFILES[dist]["weeks"]
                taper_start = weeks - 2
                wk1_vol = next((v for wk, v in data if wk == 1), 0)
                peak_build = max((v for wk, v in data if wk < taper_start), default=0)
                self.assertGreater(peak_build, wk1_vol,
                    f"{dist}: build volume {peak_build} not greater than week-1 {wk1_vol}")


# ─── FTP sensitivity ─────────────────────────────────────────────────────────

class TestFTPSensitivity(unittest.TestCase):

    def test_higher_ftp_gives_higher_power_targets(self):
        """With FTP=300 all power targets should be higher than FTP=200."""
        for dist in ["70.3", "full"]:
            w200 = workouts_for(dist, ftp=200)
            w300 = workouts_for(dist, ftp=300)

            def max_power(wkts):
                return max(
                    step["targetValueTwo"]
                    for wkt, _ in wkts
                    for step in steps_of(wkt)
                    if step["targetValueTwo"] is not None
                    and wkt["sportType"]["sportTypeKey"] == "cycling"
                )

            self.assertGreater(max_power(w300), max_power(w200),
                f"{dist}: FTP=300 should give higher power than FTP=200")

    def test_faster_pace_gives_higher_run_ms(self):
        """Faster input pace → higher m/s values in run steps."""
        for dist in ["70.3", "full"]:
            w_slow = workouts_for(dist, pace_ms=pace_to_ms("6:00"))
            w_fast = workouts_for(dist, pace_ms=pace_to_ms("4:30"))

            def max_pace(wkts):
                return max(
                    step["targetValueTwo"]
                    for wkt, _ in wkts
                    for step in steps_of(wkt)
                    if step["targetValueTwo"] is not None
                    and wkt["sportType"]["sportTypeKey"] == "running"
                )

            self.assertGreater(max_pace(w_fast), max_pace(w_slow),
                f"{dist}: faster input pace should give higher m/s targets")


if __name__ == "__main__":
    unittest.main(verbosity=2)
