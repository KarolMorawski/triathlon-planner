#!/usr/bin/env python3
"""
MyWhoosh / Zwift .zwo Generator — sync z planem Garmin
=======================================================
Generuje pliki .zwo bezpośrednio z treningów rowerowych z season_plan.py /
generate_plan.py. Format .zwo kompatybilny z MyWhoosh i Zwift:

  <Warmup>      rozgrzewka
  <Cooldown>    schłodzenie
  <SteadyState> blok stałej mocy
  <IntervalsT>  powtarzające się pary (interval+recovery)

API:
  workouts_to_zwo(workouts, ftp, output_dir, prefix)
      — konwertuje listę treningów (output generate_race_block / generate_bridge_block /
        generate_plan) do .zwo. Używane przez 4 główne skrypty po uploadzie do Garmin.

  generate_from_season_plan(race_date, distance, ftp, run_pace_ms, prefix, ...)
      — re-generuje plan z parametrów i konwertuje. Używane przez CLI.

CLI:
  python3 mywhoosh_season.py --race-date 2026-08-30 --distance 70.3 \\
      --prefix POZNAN --ftp 255 --run-pace 5:20

  python3 mywhoosh_season.py --race-date 2026-07-19 --distance 70.3 \\
      --prefix GDY --bridge-block --plan-start 2026-06-22
"""

import argparse
import sys
from datetime import date as _Date
from pathlib import Path
from triathlon_core import validate_prefix_pl as _validate_prefix

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

# ─── KONWERSJA Z PLANU GARMIN → .ZWO ─────────────────────────────────────────

def _step_power(step: dict, ftp: int) -> float:
    """Return average power as fraction of FTP from a Garmin workout step."""
    v1 = step.get("targetValueOne")
    v2 = step.get("targetValueTwo")
    if v1 is not None and v2 is not None:
        return (v1 + v2) / 2 / ftp
    if v1 is not None:
        return v1 / ftp
    return 0.65


def workout_to_zwo(wkt: dict, ftp: int) -> str:
    """
    Convert a Garmin bike workout dict (from generate_race_block) to .zwo XML.
    Consecutive (interval, recovery) pairs with equal duration/power are grouped
    into <IntervalsT> blocks; all others become <SteadyState>.
    """
    name = wkt["workoutName"]
    desc = wkt.get("description", name)
    steps = wkt["workoutSegments"][0]["workoutSteps"]
    blocks = []
    i = 0

    while i < len(steps):
        step = steps[i]
        key = step["stepType"]["stepTypeKey"]
        dur_s = int(step["endConditionValue"])

        if key == "warmup":
            blocks.append(warmup(dur_s))
            i += 1
            continue
        if key == "cooldown":
            blocks.append(cooldown(dur_s))
            i += 1
            continue

        if key == "interval":
            on_s = dur_s
            on_p = _step_power(step, ftp)

            # Try to group repeating (interval + recovery) pairs
            j = i + 1
            off_s = off_p = None
            if j < len(steps) and steps[j]["stepType"]["stepTypeKey"] == "recovery":
                off_s = int(steps[j]["endConditionValue"])
                off_p = _step_power(steps[j], ftp)
                j += 1

            if off_s is not None:
                repeat = 1
                while (j < len(steps) and
                       steps[j]["stepType"]["stepTypeKey"] == "interval" and
                       int(steps[j]["endConditionValue"]) == on_s and
                       abs(_step_power(steps[j], ftp) - on_p) < 0.01 and
                       j + 1 < len(steps) and
                       steps[j + 1]["stepType"]["stepTypeKey"] == "recovery" and
                       int(steps[j + 1]["endConditionValue"]) == off_s):
                    repeat += 1
                    j += 2

                if repeat > 1:
                    blocks.append(intervals(repeat, on_s, off_s, on_p, off_p,
                                            on_msg=f"MOCNO! @{round(on_p * ftp)}W",
                                            off_msg=f"Odpoczynek @{round(off_p * ftp)}W"))
                    i = j
                    continue
                # Not repeating — emit first pair as SteadyState
                blocks.append(steady(on_s, on_p,
                    msgs=[(0, f"{round(on_p * ftp)}W — {on_p:.0%} FTP")]))
                blocks.append(steady(off_s, off_p,
                    msgs=[(0, f"Odpoczynek @{round(off_p * ftp)}W")]))
                i = i + 2
            else:
                blocks.append(steady(on_s, on_p,
                    msgs=[(0, f"{round(on_p * ftp)}W — {on_p:.0%} FTP")]))
                i += 1
            continue

        if key == "recovery":
            p = _step_power(step, ftp)
            blocks.append(steady(dur_s, p, msgs=[(0, f"Odpoczynek @{round(p * ftp)}W")]))
            i += 1
            continue

        i += 1  # skip unknown step types

    return zwo(name, desc, blocks)


def workouts_to_zwo(workouts: list, ftp: int, output_dir: str,
                    prefix: str = None, print_footer: bool = True) -> int:
    """
    Convert ALREADY GENERATED workouts to .zwo files. Bypasses re-generation —
    guarantees byte-level sync with what was uploaded to Garmin.

    workouts: list of (workout_dict, date_str) tuples — output of generate_race_block /
              generate_bridge_block / generate_plan
    prefix: optional subfolder name (lowercased); if None, files go directly to output_dir
    """
    bike = [(w, d) for w, d in workouts if w["sportType"]["sportTypeKey"] == "cycling"]
    if not bike:
        print(f"  Brak treningów rowerowych do konwersji.")
        return 0

    out_dir = Path(output_dir) / prefix.lower() if prefix else Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for wkt, d in sorted(bike, key=lambda x: x[1]):
        content = workout_to_zwo(wkt, ftp)
        safe = wkt["workoutName"].replace("/", "-").replace(" ", "_")
        (out_dir / f"{d}_{safe}.zwo").write_text(content, encoding="utf-8")
        print(f"    ✓ {d}  {wkt['workoutName']}")
        count += 1

    print(f"  Wygenerowano: {count} plików .zwo w {out_dir.resolve()}")
    if print_footer:
        print(f"  Skopiuj do:")
        print(f"    Mac:     ~/Documents/MyWhoosh/Workouts/")
        print(f"    Windows: Documents\\MyWhoosh\\Workouts\\")
        print(f"    Zwift:   ~/Documents/Zwift/Workouts/<TWOJ_ID>/")
    return count


def generate_from_season_plan(race_date: _Date, distance: str, ftp: int,
                               run_pace_ms: float, prefix: str,
                               output_dir: str = "./mywhoosh_from_plan",
                               bridge_block: bool = False,
                               **kwargs) -> int:
    """
    Re-generate plan from scratch and write .zwo files. Used by --from-plan CLI.
    For sync with Garmin upload, prefer workouts_to_zwo() with the live workouts list.
    """
    import math
    from datetime import timedelta
    if bridge_block:
        from season_plan import generate_bridge_block
        plan_start = kwargs.get("plan_start")
        if plan_start is not None:
            ps = plan_start - timedelta(days=plan_start.weekday())
            kwargs["gap_weeks"] = math.ceil((race_date - ps).days / 7)
        workouts = generate_bridge_block(race_date, distance, ftp, run_pace_ms, prefix, **kwargs)
    else:
        from season_plan import generate_race_block
        workouts = generate_race_block(race_date, distance, ftp, run_pace_ms, prefix, **kwargs)
    return workouts_to_zwo(workouts, ftp, output_dir, prefix=prefix)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Generator .zwo dla MyWhoosh/Zwift — sync z planem Garmin")
    p.add_argument("--race-date",     required=True,
                   help="Data wyścigu YYYY-MM-DD")
    p.add_argument("--distance",      required=True,
                   choices=["sprint", "quarter", "olympic", "70.3", "full"],
                   help="Dystans wyścigu")
    p.add_argument("--prefix",        required=True,
                   help="Prefix nazw treningów (np. POZNAN)")
    p.add_argument("--ftp",           type=int, default=255,
                   help="FTP w watach (domyślnie 255)")
    p.add_argument("--run-pace",      default="5:20",
                   help="Tempo biegu MM:SS/km (domyślnie 5:20)")
    p.add_argument("--output",        default="./mywhoosh_2026",
                   help="Folder wyjściowy (domyślnie ./mywhoosh_2026)")
    p.add_argument("--bridge-block",  action="store_true",
                   help="Bridge block zamiast race block (kolejne wyścigi po pierwszym)")
    p.add_argument("--plan-start",    default=None,
                   help="Data początku planu YYYY-MM-DD (wyrówna do poniedziałku)")
    p.add_argument("--race-bike-pct", type=float, default=None,
                   help="Docelowe %% FTP na rower w wyścigu (np. 0.908 dla sub-5h 70.3)")

    args = p.parse_args()

    if args.ftp <= 0:
        p.error(f"--ftp musi być > 0 (otrzymano {args.ftp})")
    try:
        race_date = _Date.fromisoformat(args.race_date)
    except ValueError:
        p.error(f"Niepoprawna data: {args.race_date!r} — użyj formatu YYYY-MM-DD")
    try:
        from season_plan import pace_to_ms
        run_pace_ms = pace_to_ms(args.run_pace)
    except (ImportError, Exception) as e:
        p.error(f"Nie można załadować season_plan.py: {e}")

    prefix = args.prefix.upper()
    _validate_prefix(prefix)

    block_type = "bridge block" if args.bridge_block else "race block"
    print(f"\n{'='*50}")
    print(f"  MyWhoosh .zwo Generator (sync z Garmin, {block_type})")
    print(f"  Wyścig: {race_date}  Dystans: {args.distance}  Prefix: {prefix}")
    print(f"  Tempo biegu: {args.run_pace}/km  FTP: {args.ftp}W")
    print(f"{'='*50}")

    kwargs = {}
    if args.plan_start:
        try:
            kwargs["plan_start"] = _Date.fromisoformat(args.plan_start)
        except ValueError:
            p.error(f"Niepoprawna data --plan-start: {args.plan_start!r}")
    if args.race_bike_pct:
        kwargs["race_bike_pct"] = args.race_bike_pct

    generate_from_season_plan(race_date, args.distance, args.ftp, run_pace_ms,
                              prefix, args.output,
                              bridge_block=args.bridge_block, **kwargs)


if __name__ == "__main__":
    main()
