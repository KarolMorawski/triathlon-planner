#!/usr/bin/env python3
"""
Strava-Based Plan Suggestions
==============================
Analyzes recent Strava activity and suggests parameters for the plan generator.

Reads OAuth tokens from ~/.config/strava-mcp/config.json (created by strava-mcp).
Auto-refreshes the access token when expired.

Outputs:
  - Current weekly volume per sport (last 4 weeks)
  - Average training paces
  - Suggested --target-time / --run-pace for upcoming race
  - Suggested --vol-scale (volume calibration vs plan baseline)

Usage:
  python3 strava_suggest.py --distance 70.3
  python3 strava_suggest.py --distance 70.3 --weeks 8     # analyze longer window
  python3 strava_suggest.py --distance full --race-date 2026-09-15
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "strava-mcp" / "config.json"
API_BASE    = "https://www.strava.com/api/v3"

# ─── PLAN BASELINE (matches PROFILES in generate_plan.py) ────────────────────

PLAN_BASELINE = {
    "sprint":  {"swim_m":  750, "bike_km":  20, "run_km":  5,    "weeks":  8,
                "wk_swim_km": 2.5,  "wk_bike_km": 50,  "wk_run_km": 18},
    "olympic": {"swim_m": 1500, "bike_km":  40, "run_km": 10,    "weeks": 10,
                "wk_swim_km": 4,    "wk_bike_km": 90,  "wk_run_km": 30},
    "70.3":    {"swim_m": 1900, "bike_km":  90, "run_km": 21.1,  "weeks": 12,
                "wk_swim_km": 6,    "wk_bike_km": 150, "wk_run_km": 40},
    "full":    {"swim_m": 3800, "bike_km": 180, "run_km": 42.2,  "weeks": 16,
                "wk_swim_km": 8,    "wk_bike_km": 250, "wk_run_km": 60},
}

# Race vs training pace ratios — race is faster than typical aerobic training pace
# Conservative estimates from triathlon coaching literature
RACE_PACE_RATIO = {
    "sprint":  {"run": 1.08, "bike": 1.10},   # race ~8-10% faster than training
    "olympic": {"run": 1.06, "bike": 1.08},
    "70.3":    {"run": 1.04, "bike": 1.05},
    "full":    {"run": 1.00, "bike": 1.02},   # full IM = aerobic pace
}

# T1+T2 typical in minutes
T1T2_MIN = {"sprint": 5, "olympic": 7, "70.3": 10, "full": 12}

# ─── STRAVA OAUTH ────────────────────────────────────────────────────────────

def _read_config():
    if not CONFIG_PATH.exists():
        sys.exit(f"ERROR: Strava MCP config not found at {CONFIG_PATH}\n"
                 "  Set up the strava-mcp server first or place tokens manually.")
    return json.loads(CONFIG_PATH.read_text())

def _save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))

def _refresh_token(cfg):
    """Refresh expired access token using refresh token."""
    body = urllib.parse.urlencode({
        "client_id":     cfg["clientId"],
        "client_secret": cfg["clientSecret"],
        "grant_type":    "refresh_token",
        "refresh_token": cfg["refreshToken"],
    }).encode()
    req = urllib.request.Request("https://www.strava.com/oauth/token",
                                 data=body, method="POST")
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    cfg["accessToken"]  = data["access_token"]
    cfg["refreshToken"] = data["refresh_token"]
    cfg["expiresAt"]    = data["expires_at"] * 1000  # MCP stores ms
    _save_config(cfg)
    return cfg

def _get_token():
    cfg = _read_config()
    expires_at_s = cfg["expiresAt"] / 1000
    if time.time() >= expires_at_s - 60:
        print("  Refreshing expired Strava token...")
        cfg = _refresh_token(cfg)
    return cfg["accessToken"]

def _api_get(path, token, **params):
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# ─── ACTIVITY FETCH ──────────────────────────────────────────────────────────

def fetch_activities(token, weeks=4):
    """Fetch all activities from the last N weeks (paginated)."""
    after = int((datetime.now(timezone.utc) - timedelta(weeks=weeks)).timestamp())
    activities, page = [], 1
    while True:
        batch = _api_get("/athlete/activities", token,
                         after=after, page=page, per_page=200)
        if not batch:
            break
        activities.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    return activities

# ─── ANALYSIS ────────────────────────────────────────────────────────────────

def _ms_to_pace(ms):
    if ms <= 0:
        return "—"
    spk = 1000.0 / ms
    return f"{int(spk // 60)}:{int(spk % 60):02d}/km"

def _per100(ms):
    if ms <= 0:
        return "—"
    s = 100.0 / ms
    return f"{int(s // 60)}:{int(s % 60):02d}/100m"

def analyze(activities, weeks):
    """Bucket activities by sport, compute weekly averages and paces."""
    buckets = {"Run": [], "Ride": [], "VirtualRide": [], "Swim": []}
    for a in activities:
        t = a.get("type", "")
        if t in buckets:
            buckets[t].append(a)

    def _stats(acts):
        if not acts:
            return {"count": 0, "dist_km": 0, "moving_h": 0,
                    "wk_dist_km": 0, "wk_moving_h": 0,
                    "avg_speed_ms": 0}
        dist_m   = sum(a.get("distance", 0) for a in acts)
        moving_s = sum(a.get("moving_time", 0) for a in acts)
        return {
            "count":         len(acts),
            "dist_km":       round(dist_m / 1000, 1),
            "moving_h":      round(moving_s / 3600, 1),
            "wk_dist_km":    round((dist_m / 1000) / weeks, 1),
            "wk_moving_h":   round((moving_s / 3600) / weeks, 1),
            "avg_speed_ms":  (dist_m / moving_s) if moving_s > 0 else 0,
        }

    return {
        "Run":  _stats(buckets["Run"]),
        "Bike": _stats(buckets["Ride"] + buckets["VirtualRide"]),
        "Swim": _stats(buckets["Swim"]),
    }

# ─── SUGGESTIONS ─────────────────────────────────────────────────────────────

def _fmt_hms(minutes):
    total = int(round(minutes * 60))
    h, rem = divmod(total, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"

def suggest(distance, stats):
    """Return a dict with suggested plan parameters."""
    base = PLAN_BASELINE[distance]
    rp   = RACE_PACE_RATIO[distance]

    run_train_ms  = stats["Run"]["avg_speed_ms"]
    bike_train_ms = stats["Bike"]["avg_speed_ms"]
    swim_train_ms = stats["Swim"]["avg_speed_ms"]

    # Volume scale — cap at [0.5, 1.5] for sanity
    run_ratio  = stats["Run"]["wk_dist_km"]  / base["wk_run_km"]  if base["wk_run_km"]  else 1
    bike_ratio = stats["Bike"]["wk_dist_km"] / base["wk_bike_km"] if base["wk_bike_km"] else 1
    swim_ratio = stats["Swim"]["wk_dist_km"] / base["wk_swim_km"] if base["wk_swim_km"] else 1
    avg_ratio  = (run_ratio + bike_ratio + swim_ratio) / 3
    vol_scale  = max(0.5, min(1.5, round(avg_ratio, 2)))

    # Race pace projections
    run_race_ms  = run_train_ms  * rp["run"]  if run_train_ms  else 0
    bike_race_ms = bike_train_ms * rp["bike"] if bike_train_ms else 0
    swim_race_ms = swim_train_ms                                       # swim race ≈ training threshold

    # Estimated finish time (only if all 3 sports have data)
    target_time_str = None
    if run_race_ms and bike_race_ms and swim_race_ms:
        swim_min = (base["swim_m"] / swim_race_ms) / 60
        bike_min = (base["bike_km"] * 1000 / bike_race_ms) / 60
        run_min  = (base["run_km"]  * 1000 / run_race_ms)  / 60
        total_min = swim_min + bike_min + run_min + T1T2_MIN[distance]
        target_time_str = _fmt_hms(total_min)

    return {
        "vol_scale":      vol_scale,
        "ratios":         {"run": run_ratio, "bike": bike_ratio, "swim": swim_ratio},
        "run_pace_train": _ms_to_pace(run_train_ms),
        "run_pace_race":  _ms_to_pace(run_race_ms),
        "bike_kmh_train": round(bike_train_ms * 3.6, 1) if bike_train_ms else 0,
        "bike_kmh_race":  round(bike_race_ms  * 3.6, 1) if bike_race_ms  else 0,
        "swim_pace":      _per100(swim_train_ms),
        "target_time":    target_time_str,
    }

# ─── REPORT ──────────────────────────────────────────────────────────────────

def print_report(distance, race_date_str, weeks, stats, sug):
    base = PLAN_BASELINE[distance]
    print("\n" + "=" * 64)
    print(f"  Strava Plan Suggestions  ({distance} — {weeks}-week analysis)")
    if race_date_str:
        days = (date.fromisoformat(race_date_str) - date.today()).days
        print(f"  Race date: {race_date_str}  ({days} days  ≈ {days // 7} weeks away)")
    print("=" * 64)

    print(f"\n  Recent training volume (last {weeks} weeks → weekly average):\n")
    for sport in ("Run", "Bike", "Swim"):
        s = stats[sport]
        baseline = base[f"wk_{sport.lower()}_km"]
        ratio = sug["ratios"][sport.lower()]
        bar = "█" * min(20, int(ratio * 10))
        gap = "·" * max(0, 20 - len(bar))
        warn = " ⚠ low" if ratio < 0.6 else (" ↑ high" if ratio > 1.3 else "")
        print(f"    {sport:5s}  {s['wk_dist_km']:6.1f} km/wk  ({s['count']:3d} sessions, {s['wk_moving_h']:.1f} h/wk)")
        print(f"           target {baseline:5.0f} km/wk  [{bar}{gap}] {ratio:.0%}{warn}")

    print(f"\n  Average training paces:")
    print(f"    Run:  {sug['run_pace_train']}  →  race pace ~{sug['run_pace_race']}")
    print(f"    Bike: {sug['bike_kmh_train']} km/h  →  race ~{sug['bike_kmh_race']} km/h")
    print(f"    Swim: {sug['swim_pace']}")

    print(f"\n  Suggested plan parameters:\n")
    if sug["target_time"]:
        print(f"    --target-time {sug['target_time']}")
    print(f"    --run-pace    {sug['run_pace_race'].replace('/km','')}")
    print(f"    --vol-scale   {sug['vol_scale']}")

    print(f"\n  Example command:\n")
    cmd = (f"    python3 generate_plan.py --distance {distance} "
           + (f"--race-date {race_date_str} " if race_date_str else "")
           + f"--ftp <YOUR_FTP> --weight <YOUR_WEIGHT> "
           + (f"--target-time {sug['target_time']} " if sug["target_time"] else "")
           + f"--vol-scale {sug['vol_scale']}")
    print(cmd + "\n")

    # Targeted advice
    print("  Notes:")
    low = [s for s, r in sug["ratios"].items() if r < 0.6]
    high = [s for s, r in sug["ratios"].items() if r > 1.3]
    if low:
        print(f"    ⚠ {', '.join(low)} volume is below plan baseline — vol-scale will reduce overall load")
    if high:
        print(f"    ↑ {', '.join(high)} volume is above plan baseline — plan may be undertraining for you")
    if sug["vol_scale"] < 0.7:
        print(f"    💡 vol-scale {sug['vol_scale']} is conservative — current fitness suggests a gentler ramp")
    if sug["vol_scale"] > 1.2:
        print(f"    💡 vol-scale {sug['vol_scale']} is aggressive — current fitness can absorb the plan + more")
    print()

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Strava-based plan suggestions for triathlon-planner")
    p.add_argument("--distance",  choices=list(PLAN_BASELINE.keys()), required=True)
    p.add_argument("--race-date", help="Race date YYYY-MM-DD (optional)")
    p.add_argument("--weeks",     type=int, default=4, help="Analysis window in weeks (default: 4)")
    args = p.parse_args()

    print("Connecting to Strava...")
    token = _get_token()
    print(f"Fetching last {args.weeks} weeks of activity...")
    acts = fetch_activities(token, weeks=args.weeks)
    print(f"  Got {len(acts)} activities.")

    stats = analyze(acts, weeks=args.weeks)
    sug   = suggest(args.distance, stats)
    print_report(args.distance, args.race_date, args.weeks, stats, sug)

if __name__ == "__main__":
    main()
