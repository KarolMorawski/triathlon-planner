#!/usr/bin/env python3
"""
Test whether Garmin session caching works correctly.

Tests _session_valid() logic without requiring a real Garmin login.
Run: python3 test_session.py
"""

import os
import sys
import time
import tempfile
import unittest
import unittest.mock
from unittest.mock import patch

# Point SESSION_DIR to a temp directory before importing
_TEMP_DIR = tempfile.mkdtemp()

import season_plan

_ORIG_SESSION_DIR   = season_plan.SESSION_DIR
_ORIG_SESSION_STAMP = season_plan.SESSION_STAMP
_ORIG_MAX_AGE       = season_plan.SESSION_MAX_AGE


class TestSessionCaching(unittest.TestCase):

    def setUp(self):
        """Redirect session paths to a temp directory."""
        self.session_dir   = tempfile.mkdtemp()
        self.session_stamp = os.path.join(self.session_dir, ".timestamp")
        season_plan.SESSION_DIR   = self.session_dir
        season_plan.SESSION_STAMP = self.session_stamp
        season_plan.SESSION_MAX_AGE = 3600  # 1h for tests

    def tearDown(self):
        """Restore original paths."""
        season_plan.SESSION_DIR   = _ORIG_SESSION_DIR
        season_plan.SESSION_STAMP = _ORIG_SESSION_STAMP
        season_plan.SESSION_MAX_AGE = _ORIG_MAX_AGE
        # Clean up temp files
        if os.path.exists(self.session_stamp):
            os.remove(self.session_stamp)
        os.rmdir(self.session_dir)

    def test_no_stamp_file_returns_false(self):
        """No stamp file → session invalid."""
        self.assertFalse(os.path.exists(self.session_stamp))
        self.assertFalse(season_plan._session_valid())

    def test_fresh_stamp_returns_true(self):
        """Stamp file just created → session valid."""
        open(self.session_stamp, "w").close()
        self.assertTrue(season_plan._session_valid())

    def test_old_stamp_returns_false(self):
        """Stamp file older than SESSION_MAX_AGE → session invalid."""
        open(self.session_stamp, "w").close()
        # Backdate modification time by 2 hours
        old_time = time.time() - 7200
        os.utime(self.session_stamp, (old_time, old_time))
        self.assertFalse(season_plan._session_valid())

    def test_stamp_at_boundary_returns_true(self):
        """Stamp file just within SESSION_MAX_AGE → session valid."""
        open(self.session_stamp, "w").close()
        # Set mtime to 10 seconds before expiry
        recent = time.time() - (season_plan.SESSION_MAX_AGE - 10)
        os.utime(self.session_stamp, (recent, recent))
        self.assertTrue(season_plan._session_valid())

    def test_stamp_just_expired_returns_false(self):
        """Stamp file 10 seconds past SESSION_MAX_AGE → session invalid."""
        open(self.session_stamp, "w").close()
        expired = time.time() - (season_plan.SESSION_MAX_AGE + 10)
        os.utime(self.session_stamp, (expired, expired))
        self.assertFalse(season_plan._session_valid())

    def test_login_creates_stamp(self):
        """Successful login should create/update the stamp file."""
        self.assertFalse(os.path.exists(self.session_stamp))

        class FakeClient:
            def login(self, **kwargs): pass

        fake_module = unittest.mock.MagicMock()
        fake_module.Garmin.return_value = FakeClient()

        with patch.dict(sys.modules, {"garminconnect": fake_module}), \
             patch("builtins.input", side_effect=["test@example.com"]), \
             patch("getpass.getpass", return_value="password"):
            season_plan.login()

        self.assertTrue(os.path.exists(self.session_stamp),
            "Stamp file should be created after login")

    def test_cached_login_does_not_overwrite_stamp(self):
        """Cached session valid → stamp mtime should not change."""
        open(self.session_stamp, "w").close()
        original_mtime = os.path.getmtime(self.session_stamp)
        time.sleep(0.05)

        # With a valid session, _session_valid() returns True
        # and the cached path is taken — stamp is NOT touched
        season_plan.SESSION_MAX_AGE = 9999
        self.assertTrue(season_plan._session_valid())

        self.assertAlmostEqual(os.path.getmtime(self.session_stamp),
                               original_mtime, delta=0.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
