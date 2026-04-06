#!/usr/bin/env python3
"""
Integration test — Garmin OAuth token persistence (garth.dumps() approach).

This test uses a different login approach than season_plan.py:
  - Saves OAuth tokens as a base64 string (garth.dumps()) to ~/.garmin_token
  - On subsequent runs loads the token directly — no password needed
  - Tokens are refreshed automatically by garth (valid for weeks/months)
  - No 8h TTL — avoids 429 rate limit from repeated SSO logins

Modes:
  A) Token file exists → load and verify, no credentials required
  B) No token file     → fresh login (credentials required), save token

Run: python3 test_session.py
"""

import os
import getpass
import unittest
from pathlib import Path

from garminconnect import Garmin, GarminConnectAuthenticationError

TOKEN_FILE = Path.home() / ".garmin_token"


def _load_client():
    """Load Garmin client from saved OAuth token. Returns None if no token."""
    if not TOKEN_FILE.exists():
        return None
    try:
        client = Garmin()
        client.login(tokenstore=TOKEN_FILE.read_text())
        return client
    except Exception:
        return None


def _fresh_login():
    """Interactive login — saves OAuth token on success. Returns client."""
    email    = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")
    client   = Garmin(email, password, return_on_mfa=True)
    result, state = client.login()
    if result == "needs_mfa":
        mfa = input("MFA/2FA code: ").strip()
        client.resume_login(state, mfa)
    # Save OAuth token as base64 string — valid for weeks/months
    TOKEN_FILE.write_text(client.garth.dumps())
    print(f"  ✓ Token saved to {TOKEN_FILE}")
    return client


class TestGarminOAuthToken(unittest.TestCase):
    """
    Integration test — requires real Garmin credentials on first run only.
    """

    def test_token_login(self):
        """
        Case A: token file exists → load without credentials, verify API call.
        Case B: no token file    → fresh login, save token, verify API call.
        """
        client = _load_client()

        if client:
            print(f"\n✓ Token loaded from {TOKEN_FILE}")
            print("  No credentials required — testing API call...")
        else:
            print(f"\nNo token found at {TOKEN_FILE} — fresh login required.")
            try:
                client = _fresh_login()
            except (GarminConnectAuthenticationError, Exception) as e:
                if "429" in str(e) or "Rate Limit" in str(e):
                    self.skipTest(
                        "Garmin rate limit (429) — account temporarily blocked. "
                        "Wait a few hours or reset your password to unblock."
                    )
                raise

        self.assertIsNotNone(client, "Should have a valid client at this point")

        # Verify token works by making a real API call
        try:
            profile = client.get_full_name()
            print(f"  ✓ API call successful — logged in as: {profile}")
        except Exception as e:
            self.fail(f"API call failed with valid token: {e}")

    def test_token_file_survives_reload(self):
        """Token saved by previous test must be loadable in a new client instance."""
        if not TOKEN_FILE.exists():
            self.skipTest("No token file — run test_token_login first")

        client = _load_client()
        self.assertIsNotNone(client,
            f"Failed to load token from {TOKEN_FILE} — token may be corrupted")
        print(f"\n✓ Token reloaded successfully from {TOKEN_FILE}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
