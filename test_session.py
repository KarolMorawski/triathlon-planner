#!/usr/bin/env python3
"""
Integration test — Garmin session persistence.

Verifies that:
  1. First login saves a session to ~/.garmin_session
  2. Second login within 8h reuses the cached session (no password prompt)
  3. SESSION_MAX_AGE is 8 hours

Run: python3 test_session.py
Requires: real Garmin credentials (interactive prompt on first run).
"""

import os
import sys
import time
import unittest

import season_plan
from season_plan import SESSION_DIR, SESSION_STAMP, SESSION_MAX_AGE, _session_valid


class TestSessionMaxAge(unittest.TestCase):
    """Unit test — no Garmin login required."""

    def test_default_session_max_age_is_8_hours(self):
        """SESSION_MAX_AGE must be exactly 8 hours (28800 seconds)."""
        self.assertEqual(SESSION_MAX_AGE, 8 * 3600,
            f"Expected 28800 (8h), got {SESSION_MAX_AGE}")


class TestGarminSessionPersistence(unittest.TestCase):
    """
    Integration test — requires real Garmin credentials.
    Skipped automatically if SESSION_DIR already contains a valid session
    (re-running within 8h should just confirm cache is still valid).
    """

    def test_login_saves_session_and_cache_is_reused(self):
        """
        Step 1: Login to Garmin → stamp file created.
        Step 2: Call login() again → cached session used, no password prompt.
        """
        # ── Step 1: fresh login ───────────────────────────────────────────
        print("\nStep 1: Logging in to Garmin (credentials required)...")
        client1 = season_plan.login()
        self.assertIsNotNone(client1, "login() should return a client object")

        self.assertTrue(os.path.isfile(SESSION_STAMP),
            "Stamp file should exist after login")
        self.assertTrue(_session_valid(),
            "Session should be valid immediately after login")

        stamp_mtime = os.path.getmtime(SESSION_STAMP)
        print(f"  ✓ Session saved to {SESSION_DIR}")
        print(f"  ✓ Stamp mtime: {time.ctime(stamp_mtime)}")
        print(f"  ✓ Valid for: {SESSION_MAX_AGE // 3600}h "
              f"(expires ~{time.ctime(stamp_mtime + SESSION_MAX_AGE)})")

        # ── Step 2: second call should use cache ──────────────────────────
        print("\nStep 2: Calling login() again — should use cached session...")
        time.sleep(0.1)
        client2 = season_plan.login()
        self.assertIsNotNone(client2, "Cached login() should also return a client")

        # Stamp mtime should NOT change on cached login
        new_mtime = os.path.getmtime(SESSION_STAMP)
        self.assertAlmostEqual(new_mtime, stamp_mtime, delta=1.0,
            msg="Stamp mtime changed — cache was not reused, fresh login occurred")

        print("  ✓ Cached session reused (stamp mtime unchanged)")
        print(f"\n✓ Session will remain valid for "
              f"~{(stamp_mtime + SESSION_MAX_AGE - time.time()) / 3600:.1f}h")


if __name__ == "__main__":
    unittest.main(verbosity=2)
