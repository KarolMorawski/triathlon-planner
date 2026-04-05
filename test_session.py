#!/usr/bin/env python3
"""
Integration test — Garmin session persistence.

Verifies that:
  1. First login saves a session to ~/.garmin_session
  2. Second login within 8h reuses the cached session (no password prompt)
  3. SESSION_MAX_AGE is 8 hours

Run: python3 test_session.py
Requires: real Garmin credentials on first run.
On subsequent runs within 8h — only verifies that the existing cache is valid,
no credentials required.
"""

import os
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
    Integration test — behaviour depends on current session state:

    A) Valid cache exists (within 8h):
       — skips fresh login entirely
       — only verifies cache is still valid and shows remaining time

    B) No cache / expired:
       — asks for credentials (fresh login)
       — verifies stamp file created
       — verifies second login() call reuses cache without re-authenticating
    """

    def test_login_saves_session_and_cache_is_reused(self):

        # ── Case A: valid cache already exists ───────────────────────────
        if _session_valid():
            stamp_mtime = os.path.getmtime(SESSION_STAMP)
            remaining_h = (stamp_mtime + SESSION_MAX_AGE - time.time()) / 3600
            print(f"\n✓ Valid cached session found in {SESSION_DIR}")
            print(f"  Stamp created: {time.ctime(stamp_mtime)}")
            print(f"  Remaining:     ~{remaining_h:.1f}h")

            # Verify second login() call uses cache (mtime unchanged)
            time.sleep(0.1)
            client = season_plan.login()
            self.assertIsNotNone(client, "login() should return a client")
            new_mtime = os.path.getmtime(SESSION_STAMP)
            self.assertAlmostEqual(new_mtime, stamp_mtime, delta=1.0,
                msg="Stamp mtime changed — cache was not reused")
            print("  ✓ login() reused cache (stamp mtime unchanged)")
            return

        # ── Case B: no cache — fresh login required ───────────────────────
        print("\nNo cached session found — fresh login required.")
        print("Step 1: Logging in to Garmin (credentials required)...")
        try:
            client1 = season_plan.login()
        except Exception as e:
            if "429" in str(e) or "Rate Limit" in str(e):
                self.skipTest(
                    "Garmin rate limit (429) — account temporarily blocked, "
                    "wait a few hours or reset your password to unblock"
                )
            raise

        self.assertIsNotNone(client1, "login() should return a client object")
        self.assertTrue(os.path.isfile(SESSION_STAMP),
            "Stamp file should exist after login")
        self.assertTrue(_session_valid(),
            "Session should be valid immediately after login")

        stamp_mtime = os.path.getmtime(SESSION_STAMP)
        print(f"  ✓ Session saved to {SESSION_DIR}")
        print(f"  ✓ Valid for: {SESSION_MAX_AGE // 3600}h "
              f"(expires ~{time.ctime(stamp_mtime + SESSION_MAX_AGE)})")

        # Step 2: second call must reuse cache
        print("\nStep 2: Calling login() again — should use cached session...")
        time.sleep(0.1)
        client2 = season_plan.login()
        self.assertIsNotNone(client2, "Cached login() should also return a client")

        new_mtime = os.path.getmtime(SESSION_STAMP)
        self.assertAlmostEqual(new_mtime, stamp_mtime, delta=1.0,
            msg="Stamp mtime changed — cache was not reused, fresh login occurred")

        print("  ✓ Cached session reused (stamp mtime unchanged)")
        remaining_h = (stamp_mtime + SESSION_MAX_AGE - time.time()) / 3600
        print(f"\n✓ Session will remain valid for ~{remaining_h:.1f}h")


if __name__ == "__main__":
    unittest.main(verbosity=2)
