#!/usr/bin/env python3
"""
MyWhoosh / Zwift .zwo Generator
=================================
Poprawiony format .zwo kompatybilny z MyWhoosh i Zwift.

- <Warmup>     dla rozgrzewki
- <Cooldown>   dla schłodzenia
- <SteadyState> dla bloków stałej mocy
- <IntervalsT> dla interwałów threshold/VO2max
- Wiadomości tekstowe z wskazówkami treningowymi

Usage:
  python3 mywhoosh_season.py
  python3 mywhoosh_season.py --ftp 255 --output ./moje_treningi
  python3 mywhoosh_season.py --race poznan --ftp 260
  python3 mywhoosh_season.py --list
"""

import argparse
import re
import sys
from pathlib import Path
from dataclasses import dataclass

_PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")

def _validate_prefix(p):
    """Reject prefixes that could escape the output dir or contain unsafe characters."""
    if not _PREFIX_RE.match(p):
        sys.exit(f"BŁĄD: Niepoprawny prefix '{p}'. Dozwolone: A-Z, 0-9, _, - (musi zaczynać się od znaku alfanumerycznego).")

# ─── KONFIGURACJA ─────────────────────────────────────────────────────────────

@dataclass
class Zone:
    lo: float  # % FTP dolna
    hi: float  # % FTP górna

    def avg(self): return (self.lo + self.hi) / 2
    def watts_lo(self, ftp): return round(ftp * self.lo)
    def watts_hi(self, ftp): return round(ftp * self.hi)
    def watts_avg(self, ftp): return round(ftp * self.avg())

ZONES = {
    "z1":    Zone(0.40, 0.55),
    "z2":    Zone(0.60, 0.72),
    "z3":    Zone(0.76, 0.87),
    "z4":    Zone(0.88, 0.97),
    "z5":    Zone(1.02, 1.12),
    "race":  Zone(0.79, 0.85),   # Race effort 70.3
    "wu":    Zone(0.50, 0.65),   # Warmup
    "cd":    Zone(0.40, 0.55),   # Cooldown
}

# ─── ELEMENTY XML ─────────────────────────────────────────────────────────────

def warmup(duration_s: int, lo: float = 0.50, hi: float = 0.65,
           msg: str = "Rozgrzewka — zacznij spokojnie") -> str:
    return (f'    <Warmup Duration="{duration_s}" PowerLow="{lo:.2f}" PowerHigh="{hi:.2f}">\n'
            f'      <textevent timeoffset="0" message="{msg}"/>\n'
            f'    </Warmup>')

def cooldown(duration_s: int, lo: float = 0.65, hi: float = 0.40,
             msg: str = "Schłodzenie — zredukuj moc stopniowo") -> str:
    return (f'    <Cooldown Duration="{duration_s}" PowerLow="{lo:.2f}" PowerHigh="{hi:.2f}">\n'
            f'      <textevent timeoffset="0" message="{msg}"/>\n'
            f'    </Cooldown>')

def steady(duration_s: int, power: float, msgs: list = None) -> str:
    lines = [f'    <SteadyState Duration="{duration_s}" Power="{power:.2f}">']
    if msgs:
        for offset, msg in msgs:
            lines.append(f'      <textevent timeoffset="{offset}" message="{msg}"/>')
    else:
        lines.append(f'      <textevent timeoffset="0" message="Trzymaj moc — {power:.0%} FTP"/>')
    lines.append('    </SteadyState>')
    return '\n'.join(lines)

def intervals(repeat: int, on_s: int, off_s: int,
              on_power: float, off_power: float,
              on_msg: str = "MOCNO!", off_msg: str = "Odpoczynek") -> str:
    return (f'    <IntervalsT Repeat="{repeat}" '
            f'OnDuration="{on_s}" OffDuration="{off_s}" '
            f'OnPower="{on_power:.2f}" OffPower="{off_power:.2f}">\n'
            f'      <textevent timeoffset="0" message="{on_msg}"/>\n'
            f'      <textevent timeoffset="{on_s}" message="{off_msg}"/>\n'
            f'    </IntervalsT>')

def free(duration_s: int, msg: str = "Wolne tempo") -> str:
    return (f'    <FreeRide Duration="{duration_s}">\n'
            f'      <textevent timeoffset="0" message="{msg}"/>\n'
            f'    </FreeRide>')

# ─── BUILDER PLIKU ZWO ────────────────────────────────────────────────────────

def zwo(name: str, description: str, blocks: list, author: str = "Triathlon Planner") -> str:
    body = '\n'.join(blocks)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<workout_file>
  <author>{author}</author>
  <name>{name}</name>
  <description>{description}</description>
  <sportType>bike</sportType>
  <tags/>
  <workout>
{body}
  </workout>
</workout_file>'''

# ─── GENERATORY TRENINGÓW ─────────────────────────────────────────────────────

def make_z2_endurance(prefix: str, week: int, duration_min: int, ftp: int) -> tuple:
    if duration_min < 20:
        raise ValueError(f"Z2 endurance duration must be ≥20min (got {duration_min})")
    z = ZONES["z2"]
    main_s = duration_min * 60 - 900  # minus 10min warmup + 5min cooldown
    mid    = main_s // 2
    name   = f"{prefix}-T{week:02d} Z2 Endurance {duration_min}min"
    desc   = f"Z2 @{z.watts_lo(ftp)}-{z.watts_hi(ftp)}W ({z.lo:.0%}-{z.hi:.0%} FTP={ftp}W)"
    blocks = [
        warmup(600, msg="Rozgrzewka 10min"),
        steady(main_s, z.avg(), msgs=[
            (0,   f"Z2 Endurance @{z.watts_avg(ftp)}W — oddychaj swobodnie"),
            (900, "15min za Tobą — utrzymaj tempo"),
            (mid, "Połowa — dobra robota"),
        ]),
        cooldown(300, msg="Schłodzenie 5min"),
    ]
    return name, zwo(name, desc, blocks)

def make_threshold(prefix: str, week: int, intervals_x3: bool, ftp: int) -> tuple:
    z4 = ZONES["z4"]
    z2 = ZONES["z2"]
    z1 = ZONES["z1"]
    if intervals_x3:
        name = f"{prefix}-T{week:02d} Threshold 3x20min"
        desc = f"Threshold 3x20min @{z4.watts_lo(ftp)}-{z4.watts_hi(ftp)}W (FTP={ftp}W)"
        blocks = [
            warmup(900, msg="Rozgrzewka 15min"),
            steady(900, z2.avg(), msgs=[(0, "Z2 przygotowanie 15min")]),
            intervals(3, 1200, 300, z4.avg(), z1.avg(),
                      on_msg=f"Threshold @{z4.watts_avg(ftp)}W — mocno ale kontrolowanie",
                      off_msg=f"Odpoczynek Z1 @{z1.watts_avg(ftp)}W"),
            cooldown(600, msg="Schłodzenie 10min"),
        ]
    else:
        name = f"{prefix}-T{week:02d} Threshold 2x20min"
        desc = f"Threshold 2x20min @{z4.watts_lo(ftp)}-{z4.watts_hi(ftp)}W (FTP={ftp}W)"
        blocks = [
            warmup(900, msg="Rozgrzewka 15min"),
            intervals(2, 1200, 300, z4.avg(), z1.avg(),
                      on_msg=f"Threshold @{z4.watts_avg(ftp)}W",
                      off_msg="Odpoczynek Z1"),
            cooldown(600, msg="Schłodzenie 10min"),
        ]
    return name, zwo(name, desc, blocks)

def make_race_sim(prefix: str, week: int, duration_min: int, ftp: int) -> tuple:
    if duration_min < 30:
        raise ValueError(f"Race sim duration must be ≥30min (got {duration_min})")
    z      = ZONES["race"]
    main_s = duration_min * 60 - 1500  # minus 15min warmup + 10min cooldown
    mid    = main_s // 2
    name   = f"{prefix}-T{week:02d} Race Sim {duration_min}min"
    desc   = f"Race Simulation @{z.watts_lo(ftp)}-{z.watts_hi(ftp)}W ({z.lo:.0%}-{z.hi:.0%} FTP={ftp}W)"
    blocks = [
        warmup(900, msg="Rozgrzewka 15min — jak na wyścigu"),
        steady(main_s, z.avg(), msgs=[
            (0,            f"Race Sim @{z.watts_avg(ftp)}W — tempo wyścigu"),
            (900,          "15min — sprawdź moc i tętno"),
            (mid,          "Połowa bloku — jak się czujesz? Trzymaj moc"),
            (main_s - 600, "Ostatnie 10min — możesz mocniej"),
        ]),
        cooldown(600, msg="Schłodzenie 10min"),
    ]
    return name, zwo(name, desc, blocks)

def make_over_under(prefix: str, week: int, ftp: int) -> tuple:
    z2    = ZONES["z2"]
    over  = round(ftp * 1.04)
    under = round(ftp * 0.88)
    name  = f"{prefix}-T{week:02d} Over-Under 70min"
    desc  = f"Over-Under: {over}W (over) / {under}W (under) — FTP={ftp}W"
    blocks = [
        warmup(900, msg="Rozgrzewka 15min"),
        steady(600, z2.avg(), msgs=[(0, "Z2 aktywacja 10min")]),
        intervals(8, 120, 120,
                  round(ftp * 1.04) / ftp,
                  round(ftp * 0.88) / ftp,
                  on_msg=f"OVER @{over}W — powyżej FTP!",
                  off_msg=f"Under @{under}W — utrzymaj oddech"),
        steady(600, z2.avg(), msgs=[(0, "Z2 regeneracja 10min")]),
        cooldown(300, msg="Schłodzenie 5min"),
    ]
    return name, zwo(name, desc, blocks)

def make_vo2max(prefix: str, week: int, ftp: int) -> tuple:
    z5   = ZONES["z5"]
    z1   = ZONES["z1"]
    name = f"{prefix}-T{week:02d} VO2max 6x3min"
    desc = f"VO2max 6x3min @{z5.watts_lo(ftp)}-{z5.watts_hi(ftp)}W — FTP={ftp}W"
    blocks = [
        warmup(900, msg="Rozgrzewka 15min"),
        steady(600, ZONES["z2"].avg(), msgs=[(0, "Z2 przygotowanie")]),
        intervals(6, 180, 180, z5.avg(), z1.avg(),
                  on_msg=f"VO2max @{z5.watts_avg(ftp)}W — 3min mocno!",
                  off_msg=f"Odpoczynek @{z1.watts_avg(ftp)}W — oddychaj"),
        cooldown(600, msg="Schłodzenie 10min"),
    ]
    return name, zwo(name, desc, blocks)

def make_brick(prefix: str, week: int, duration_min: int, ftp: int) -> tuple:
    if duration_min < 30:
        raise ValueError(f"Brick duration must be ≥30min (got {duration_min})")
    z      = ZONES["race"]
    main_s = duration_min * 60 - 1500
    name   = f"{prefix}-T{week:02d} Brick Bike {duration_min}min"
    desc   = f"Brick training — natychmiast biegnij po zakończeniu! @{z.watts_lo(ftp)}-{z.watts_hi(ftp)}W"
    blocks = [
        warmup(900, msg="Rozgrzewka 15min"),
        steady(main_s, z.avg(), msgs=[
            (0,            f"Brick Ride @{z.watts_avg(ftp)}W — zaraz będziesz biegać"),
            (main_s - 300, "Ostatnie 5min — przygotuj buty do biegu!"),
        ]),
        cooldown(600, msg="Schłodzenie — nie siadaj, idź prosto na buty do biegu"),
    ]
    return name, zwo(name, desc, blocks)

def make_taper(prefix: str, week: int, duration_min: int, ftp: int) -> tuple:
    if duration_min < 20:
        raise ValueError(f"Taper duration must be ≥20min (got {duration_min})")
    z      = ZONES["z2"]
    main_s = duration_min * 60 - 900
    name   = f"{prefix}-T{week:02d} Taper Spin {duration_min}min"
    desc   = f"Tapering — lekkie Z2 @{z.watts_lo(ftp)}-{z.watts_hi(ftp)}W (FTP={ftp}W)"
    blocks = [
        warmup(600, msg="Delikatna rozgrzewka"),
        steady(main_s, z.avg(), msgs=[
            (0, f"Lekki spin @{z.watts_avg(ftp)}W — zachowaj nogi na wyścig"),
        ]),
        intervals(3, 20, 40, 1.05, z.avg(),
                  on_msg="Krótka akceleracja — obudź nogi",
                  off_msg="Luz"),
        cooldown(300, msg="Schłodzenie"),
    ]
    return name, zwo(name, desc, blocks)

def make_prerace(prefix: str, week: int, ftp: int) -> tuple:
    z    = ZONES["z2"]
    name = f"{prefix}-T{week:02d} Pre-Race Check 20min"
    desc = "Aktywacja dzień przed wyścigiem — lekki spin z akcelami"
    blocks = [
        warmup(300, msg="Delikatna rozgrzewka 5min"),
        steady(600, z.avg(), msgs=[(0, f"Lekki Z2 @{z.watts_avg(ftp)}W")]),
        intervals(3, 15, 30, 1.05, 0.55,
                  on_msg="Krótka akceleracja — sprawdź czy nogi działają",
                  off_msg="Luz"),
        steady(300, z.avg(), msgs=[(0, "Spokojnie do końca")]),
        cooldown(180, msg="Gotowy na jutro!"),
    ]
    return name, zwo(name, desc, blocks)

# ─── PLANY WEDŁUG DYSTANSU ────────────────────────────────────────────────────

# Plany dla generate_for_distance() — skalują się z dystansem
DISTANCE_WORKOUTS = {
    "sprint": [
        (1, "z2",         {"duration_min": 60}),
        (2, "threshold",  {"intervals_x3": False}),
        (3, "race_sim",   {"duration_min": 45}),
        (4, "over_under", {}),
        (5, "vo2max",     {}),
        (6, "brick",      {"duration_min": 60}),
        (7, "taper",      {"duration_min": 30}),
        (7, "prerace",    {}),
    ],
    "olympic": [
        (1,  "z2",        {"duration_min": 60}),
        (2,  "threshold", {"intervals_x3": False}),
        (3,  "z2",        {"duration_min": 75}),
        (4,  "race_sim",  {"duration_min": 60}),
        (5,  "over_under",{}),
        (6,  "vo2max",    {}),
        (7,  "z2",        {"duration_min": 90}),
        (8,  "brick",     {"duration_min": 90}),
        (9,  "taper",     {"duration_min": 40}),
        (9,  "prerace",   {}),
    ],
    "70.3": [
        (1,  "z2",        {"duration_min": 60}),
        (2,  "threshold", {"intervals_x3": False}),
        (3,  "z2",        {"duration_min": 75}),
        (4,  "race_sim",  {"duration_min": 90}),
        (5,  "threshold", {"intervals_x3": True}),
        (6,  "z2",        {"duration_min": 90}),
        (7,  "over_under",{}),
        (8,  "vo2max",    {}),
        (9,  "brick",     {"duration_min": 120}),
        (10, "race_sim",  {"duration_min": 90}),
        (11, "taper",     {"duration_min": 45}),
        (11, "prerace",   {}),
    ],
    "full": [
        (1,  "z2",        {"duration_min": 90}),
        (2,  "threshold", {"intervals_x3": False}),
        (3,  "z2",        {"duration_min": 90}),
        (4,  "race_sim",  {"duration_min": 105}),
        (5,  "threshold", {"intervals_x3": True}),
        (6,  "z2",        {"duration_min": 105}),
        (7,  "over_under",{}),
        (8,  "vo2max",    {}),
        (9,  "z2",        {"duration_min": 120}),
        (10, "brick",     {"duration_min": 150}),
        (11, "over_under",{}),
        (12, "race_sim",  {"duration_min": 120}),
        (13, "brick",     {"duration_min": 150}),
        (14, "race_sim",  {"duration_min": 90}),
        (15, "taper",     {"duration_min": 45}),
        (15, "prerace",   {}),
    ],
}

GENERATORS = {
    "z2":         lambda p, w, ftp, kw: make_z2_endurance(p, w, kw["duration_min"], ftp),
    "threshold":  lambda p, w, ftp, kw: make_threshold(p, w, kw.get("intervals_x3", True), ftp),
    "race_sim":   lambda p, w, ftp, kw: make_race_sim(p, w, kw["duration_min"], ftp),
    "over_under": lambda p, w, ftp, kw: make_over_under(p, w, ftp),
    "vo2max":     lambda p, w, ftp, kw: make_vo2max(p, w, ftp),
    "brick":      lambda p, w, ftp, kw: make_brick(p, w, kw["duration_min"], ftp),
    "taper":      lambda p, w, ftp, kw: make_taper(p, w, kw["duration_min"], ftp),
    "prerace":    lambda p, w, ftp, kw: make_prerace(p, w, ftp),
}

# ─── PLANY WEDŁUG NAZWY ZAWODÓW ───────────────────────────────────────────────

RACE_PLAN = {
    "warsaw": {
        "label": "IronMan Warsaw 70.3",
        "workouts": [
            (1,  "z2",        {"duration_min": 60}),
            (2,  "threshold", {"intervals_x3": False}),
            (3,  "z2",        {"duration_min": 75}),
            (4,  "race_sim",  {"duration_min": 90}),
            (5,  "threshold", {"intervals_x3": True}),
            (6,  "z2",        {"duration_min": 90}),
            (7,  "over_under",{}),
            (8,  "brick",     {"duration_min": 120}),
            (8,  "vo2max",    {}),
            (9,  "taper",     {"duration_min": 45}),
            (9,  "prerace",   {}),
        ]
    },
    "gdansk": {
        "label": "Challenge Gdansk 70.3",
        "workouts": [
            (1, "z2",        {"duration_min": 60}),
            (2, "race_sim",  {"duration_min": 90}),
            (3, "threshold", {"intervals_x3": True}),
            (4, "over_under",{}),
            (5, "brick",     {"duration_min": 90}),
            (6, "taper",     {"duration_min": 40}),
            (6, "prerace",   {}),
        ]
    },
    "gdynia": {
        "label": "IronMan Gdynia 70.3",
        "workouts": [
            (1,  "z2",        {"duration_min": 75}),
            (2,  "threshold", {"intervals_x3": True}),
            (3,  "race_sim",  {"duration_min": 105}),
            (4,  "over_under",{}),
            (5,  "vo2max",    {}),
            (6,  "z2",        {"duration_min": 90}),
            (7,  "brick",     {"duration_min": 120}),
            (8,  "race_sim",  {"duration_min": 90}),
            (9,  "taper",     {"duration_min": 45}),
            (9,  "prerace",   {}),
        ]
    },
    "krakow": {
        "label": "IronMan Krakow 70.3",
        "workouts": [
            (1,  "z2",        {"duration_min": 60}),
            (2,  "threshold", {"intervals_x3": True}),
            (3,  "over_under",{}),
            (4,  "race_sim",  {"duration_min": 105}),
            (5,  "vo2max",    {}),
            (6,  "z2",        {"duration_min": 90}),
            (7,  "brick",     {"duration_min": 120}),
            (8,  "race_sim",  {"duration_min": 100}),
            (9,  "taper",     {"duration_min": 45}),
            (9,  "prerace",   {}),
        ]
    },
    "poznan": {
        "label": "IronMan Poznan 70.3 — SUB5H",
        "workouts": [
            (1,  "z2",        {"duration_min": 90}),
            (2,  "threshold", {"intervals_x3": True}),
            (3,  "over_under",{}),
            (4,  "race_sim",  {"duration_min": 120}),
            (5,  "vo2max",    {}),
            (6,  "over_under",{}),
            (7,  "brick",     {"duration_min": 150}),
            (8,  "race_sim",  {"duration_min": 120}),
            (9,  "taper",     {"duration_min": 45}),
            (9,  "prerace",   {}),
        ]
    },
}

# ─── FUNKCJE GENEROWANIA ──────────────────────────────────────────────────────

def _write_workouts(prefix: str, workouts: list, ftp: int, out_dir: Path) -> int:
    """Generate .zwo files from a workout list. Returns count of files written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for week, wtype, kwargs in workouts:
        gen = GENERATORS.get(wtype)
        if not gen:
            continue
        name, content = gen(prefix, week, ftp, kwargs)
        filename = name.replace("/", "-").replace(" ", "_") + ".zwo"
        (out_dir / filename).write_text(content, encoding="utf-8")
        print(f"    ✓ {filename}")
        count += 1
    return count


def generate_for_distance(prefix: str, distance: str, ftp: int,
                          output_dir: str = "./mywhoosh") -> int:
    """
    Generate .zwo files for a given distance (sprint/olympic/70.3/full).
    Uses pre-built distance-based workout plans.
    Returns number of files generated.
    """
    workouts = DISTANCE_WORKOUTS.get(distance)
    if not workouts:
        print(f"  Nieznany dystans: {distance}. Dostępne: {list(DISTANCE_WORKOUTS)}")
        return 0

    out_dir = Path(output_dir) / prefix.lower()
    print(f"\n  .zwo — {prefix} ({distance}, {len(workouts)} treningów):")
    count = _write_workouts(prefix, workouts, ftp, out_dir)
    print(f"  Lokalizacja: {out_dir.resolve()}")
    print(f"  Skopiuj do:")
    print(f"    Mac:     ~/Documents/MyWhoosh/Workouts/")
    print(f"    Windows: Documents\\MyWhoosh\\Workouts\\")
    print(f"    Zwift:   ~/Documents/Zwift/Workouts/<TWOJ_ID>/")
    return count


def generate(races: list, ftp: int, output_dir: str):
    """Generate .zwo files for named races from RACE_PLAN."""
    base  = Path(output_dir)
    total = 0
    for race in races:
        plan = RACE_PLAN.get(race)
        if not plan:
            print(f"  Nieznane zawody: {race}")
            continue
        out_dir = base / race
        print(f"\n  {plan['label']} ({len(plan['workouts'])} treningów):")
        total += _write_workouts(race.upper(), plan["workouts"], ftp, out_dir)

    print(f"\n  Wygenerowano: {total} plików .zwo w {base.resolve()}")
    print(f"  Skopiuj do:")
    print(f"    Mac:     ~/Documents/MyWhoosh/Workouts/")
    print(f"    Windows: Documents\\MyWhoosh\\Workouts\\")
    print(f"    Zwift:   ~/Documents/Zwift/Workouts/<TWOJ_ID>/")

# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Generator .zwo dla MyWhoosh/Zwift")
    p.add_argument("--ftp",      type=int, default=255,
                   help="FTP w watach (domyślnie 255)")
    p.add_argument("--output",   default="./mywhoosh_2026",
                   help="Folder wyjściowy (domyślnie ./mywhoosh_2026)")
    p.add_argument("--race",     nargs="+",
                   choices=list(RACE_PLAN.keys()) + ["all"],
                   default=["all"],
                   help="Które zawody wygenerować (po nazwie)")
    p.add_argument("--distance", choices=list(DISTANCE_WORKOUTS.keys()),
                   help="Generuj plan według dystansu zamiast nazwy zawodów")
    p.add_argument("--prefix",   default="RACE",
                   help="Prefix nazw treningów gdy używasz --distance (domyślnie RACE)")
    p.add_argument("--list",     action="store_true",
                   help="Wyświetl dostępne zawody i dystanse")
    args = p.parse_args()

    if args.ftp <= 0:
        p.error(f"--ftp musi być > 0 (otrzymano {args.ftp})")

    if args.list:
        print("\nDostępne zawody (--race):")
        for key, plan in RACE_PLAN.items():
            print(f"  {key:10s} — {plan['label']} ({len(plan['workouts'])} treningów)")
        print("\nDostępne dystanse (--distance):")
        for key, wkts in DISTANCE_WORKOUTS.items():
            print(f"  {key:10s} — {len(wkts)} treningów")
        return

    print(f"\n{'='*50}")
    print(f"  MyWhoosh .zwo Generator")
    print(f"  FTP: {args.ftp}W")
    print(f"{'='*50}")

    if args.distance:
        prefix = args.prefix.upper()
        _validate_prefix(prefix)
        generate_for_distance(prefix, args.distance, args.ftp, args.output)
    else:
        races = list(RACE_PLAN.keys()) if "all" in args.race else args.race
        print(f"  Zawody: {', '.join(races)}")
        generate(races, args.ftp, args.output)


if __name__ == "__main__":
    main()
