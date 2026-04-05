TRIATHLON SEASON PLANNER
========================
QUICK START:
  1. pip install garminconnect
  2. Edit season_example.json with your races
  3. python3 season_plan.py --config season_example.json --reset

COMMANDS:
  python3 season_plan.py --reset                         interactive
  python3 season_plan.py --config season_example.json --reset
  python3 season_plan.py --dry-run                       preview only

DISTANCES: 70.3 / full / olympic / sprint
FULL GUIDE: open INSTRUKCJA.html in Chrome/Firefox

USING garmin-venv (recommended)
================================
The repo includes a ready-made virtual environment in garmin-venv/.
Use it to avoid installing garminconnect system-wide.

  macOS / Linux:
    source garmin-venv/bin/activate
    python3 season_plan.py --config season_example.json --reset
    deactivate                          # when done

  Windows (PowerShell):
    garmin-venv\Scripts\Activate.ps1
    python season_plan.py --config season_example.json --reset
    deactivate

  Windows (CMD):
    garmin-venv\Scripts\activate.bat
    python season_plan.py --config season_example.json --reset
    deactivate

While the venv is active your prompt will show (garmin-venv).
To recreate the venv from scratch:
    python3 -m venv garmin-venv
    source garmin-venv/bin/activate
    pip install garminconnect
