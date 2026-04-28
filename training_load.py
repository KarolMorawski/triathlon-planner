#!/usr/bin/env python3
"""
training_load.py — Planowane obciążenie treningowe (TSS/CTL/ATL/TSB)
=====================================================================
Wczytuje zapisany plan z ~/.triathlon_plans/{PREFIX}.json, regeneruje
strukturę treningów i szacuje TSS dla każdej sesji. Na tej podstawie
rysuje sezsonową krzywą formy (CTL), zmęczenia (ATL) i dyspozycji (TSB).

Nie wymaga połączenia z Garmin — działa wyłącznie na lokalnych danych.

Użycie:
  python3 training_load.py --prefix WARSAW
  python3 training_load.py --prefix WARSAW --weeks 4   # tylko ostatnie 4 tygodnie
  python3 training_load.py --list
"""

import argparse
import json
import math
import os
import sys
from datetime import date, timedelta

STATE_DIR = os.path.expanduser("~/.triathlon_plans")


# ─── STAN ─────────────────────────────────────────────────────────────────────

def load_state(prefix):
    path = os.path.join(STATE_DIR, f"{prefix}.json")
    if not os.path.exists(path):
        sys.exit(
            f"BŁĄD: Brak pliku stanu dla '{prefix}'  ({path})\n"
            f"  Uruchom najpierw season_plan.py lub generate_plan.py."
        )
    with open(path) as f:
        return json.load(f)


def list_plans():
    if not os.path.exists(STATE_DIR):
        print("Brak zapisanych planów.")
        return
    files = sorted(f for f in os.listdir(STATE_DIR) if f.endswith(".json"))
    today = date.today()
    print(f"Zapisane plany ({STATE_DIR}):\n")
    for fname in files:
        try:
            with open(os.path.join(STATE_DIR, fname)) as fp:
                st = json.load(fp)
            cfg = st.get("config", {})
            wkts = st.get("workouts", [])
            done = sum(1 for w in wkts if date.fromisoformat(w["date"]) < today)
            print(f"  {st['prefix']:15s}  {cfg.get('race_date')}  {cfg.get('distance'):6s}  "
                  f"ftp={cfg.get('ftp')}W  wykonano={done}/{len(wkts)}")
        except Exception:
            pass


# ─── TSS ESTIMATION ────────────────────────────────────────────────────────────

def _step_time(step):
    """Zwraca szacowany czas trwania kroku w sekundach."""
    ec = step.get("endCondition", {})
    val = step.get("endConditionValue", 0)
    if ec.get("conditionTypeKey") == "time":
        return float(val)
    if ec.get("conditionTypeKey") == "distance":
        # Oblicz czas z tempa/prędkości
        v1 = step.get("targetValueOne")
        v2 = step.get("targetValueTwo")
        pace = (v1 + v2) / 2 if v1 and v2 else (v1 or v2)
        if pace and pace > 0:
            return float(val) / pace
    return 0.0


def estimate_tss_bike(steps, ftp):
    """TSS rowerowy metodą NP × IF. NP = (Σ t·p⁴ / Σ t)^(1/4)."""
    total_t = 0.0
    sum_p4t = 0.0
    z1_mid = ftp * 0.475

    for s in steps:
        t = _step_time(s)
        if t <= 0:
            continue
        v1, v2 = s.get("targetValueOne"), s.get("targetValueTwo")
        key = s.get("stepType", {}).get("stepTypeKey", "")
        if v1 and v2:
            p = (v1 + v2) / 2
        elif key in ("warmup", "cooldown", "rest"):
            p = z1_mid
        else:
            p = z1_mid
        total_t += t
        sum_p4t += t * (p ** 4)

    if total_t < 60:
        return 0.0
    np_power = (sum_p4t / total_t) ** 0.25
    if_val   = np_power / ftp
    return (total_t * np_power * if_val) / (ftp * 3600) * 100


def estimate_tss_run(steps, run_pace_ms):
    """rTSS: Σ (t × (pace/threshold)²) / 36."""
    if not run_pace_ms or run_pace_ms <= 0:
        return 0.0

    total_if2t = 0.0
    total_t    = 0.0

    for s in steps:
        t = _step_time(s)
        if t <= 0:
            continue
        v1, v2 = s.get("targetValueOne"), s.get("targetValueTwo")
        key = s.get("stepType", {}).get("stepTypeKey", "")
        if v1 and v2:
            pace = (v1 + v2) / 2
        elif key in ("warmup", "cooldown"):
            pace = run_pace_ms * 0.75
        else:
            pace = run_pace_ms
        if_val = pace / run_pace_ms
        total_t    += t
        total_if2t += t * (if_val ** 2)

    if total_t < 60:
        return 0.0
    return total_if2t / 36.0


def estimate_tss_swim(steps):
    """sTSS uproszczony: ~50 TSS/h umiarkowanego pływania."""
    total_t = sum(_step_time(s) for s in steps)
    return total_t / 3600.0 * 50.0


def estimate_tss(wkt, ftp, run_pace_ms):
    """Szacuje TSS treningu na podstawie struktury kroków."""
    sport  = wkt["sportType"]["sportTypeKey"]
    steps  = wkt["workoutSegments"][0]["workoutSteps"]

    if sport == "cycling":
        return round(estimate_tss_bike(steps, ftp), 1)
    elif sport == "running":
        return round(estimate_tss_run(steps, run_pace_ms), 1)
    elif sport == "swimming":
        return round(estimate_tss_swim(steps), 1)
    return 0.0


# ─── CTL / ATL / TSB ──────────────────────────────────────────────────────────

def compute_load(daily_tss, start, end):
    """
    PMC: exponential weighted averages.
      CTL (fitness):  TC = 42 dni
      ATL (fatigue):  TC = 7 dni
      TSB (form):     CTL - ATL
    """
    k_ctl = 1 - math.exp(-1 / 42)
    k_atl = 1 - math.exp(-1 / 7)
    ctl = atl = 0.0
    result = {}
    d = start
    while d <= end:
        tss = daily_tss.get(d.isoformat(), 0.0)
        ctl = ctl + k_ctl * (tss - ctl)
        atl = atl + k_atl * (tss - atl)
        result[d] = {"tss": round(tss, 1), "ctl": round(ctl, 1),
                     "atl": round(atl, 1), "tsb": round(ctl - atl, 1)}
        d += timedelta(days=1)
    return result


# ─── WIZUALIZACJA ─────────────────────────────────────────────────────────────

def _bar(val, max_val, width=20):
    n = int(round(val / max_val * width)) if max_val > 0 else 0
    n = max(0, min(width, n))
    return "█" * n + "·" * (width - n)


def print_report(state, pmc, workouts_by_date, race_date, show_weeks=None):
    cfg    = state["config"]
    prefix = state["prefix"]
    today  = date.today()

    print(f"\n{'═'*64}")
    print(f"  TRAINING LOAD — {prefix}  ({cfg['race_date']}  {cfg['distance']})")
    print(f"  FTP: {cfg['ftp']}W  |  Vol scale: {cfg.get('vol_scale', 1.0)}")
    print(f"{'═'*64}")
    print(f"  {'Tydzień':<12} {'TSS':>5}  CTL  ATL  TSB  obciążenie")
    print(f"  {'─'*60}")

    # Iteruj tygodniami
    all_dates = sorted(pmc.keys())
    week_start = all_dates[0] - timedelta(days=all_dates[0].weekday())
    max_wk_tss = 1.0

    weeks_data = []
    d = week_start
    while d <= race_date:
        wk_tss   = sum(pmc.get(d + timedelta(i), {}).get("tss", 0) for i in range(7))
        wk_end   = d + timedelta(days=6)
        end_pmc  = pmc.get(min(wk_end, race_date))
        if end_pmc:
            max_wk_tss = max(max_wk_tss, wk_tss)
        weeks_data.append((d, wk_tss, end_pmc))
        d += timedelta(weeks=1)

    if show_weeks:
        weeks_data = weeks_data[-show_weeks:]

    for wk_start_d, wk_tss, end_pmc in weeks_data:
        wk_end_d = wk_start_d + timedelta(days=6)
        if not end_pmc:
            continue

        is_race_wk  = wk_start_d <= race_date <= wk_end_d
        is_future   = wk_start_d > today
        is_taper    = (not is_race_wk) and (race_date - wk_end_d).days < 21

        label = f"{wk_start_d.strftime('%d.%m')}"
        if is_race_wk:
            label += " 🏁"
        elif is_taper:
            label += " ↓ "
        elif is_future:
            label += " ○ "

        ctl = end_pmc["ctl"]
        atl = end_pmc["atl"]
        tsb = end_pmc["tsb"]
        bar = _bar(wk_tss, max_wk_tss * 1.1)
        tsb_sym = ("▲" if tsb > 10 else ("▼" if tsb < -20 else "~"))

        print(f"  {label:<12} {wk_tss:>5.0f}  {ctl:>3.0f}  {atl:>3.0f}  "
              f"{tsb:>+4.0f} {tsb_sym}  [{bar}]")

    # Peak CTL i forma przed wyścigiem
    race_pmc = pmc.get(race_date)
    if race_pmc:
        print(f"\n  Dzień wyścigu ({race_date}):")
        print(f"    CTL (forma):    {race_pmc['ctl']:.1f}")
        print(f"    ATL (zmęczenie):{race_pmc['atl']:.1f}")
        print(f"    TSB (dyspozycja):{race_pmc['tsb']:+.1f}  "
              f"({'dobra ✓' if 5 < race_pmc['tsb'] < 25 else 'za niska — wydłuż taper' if race_pmc['tsb'] < 5 else 'za wysoka — skróć taper'})")

    peak_ctl_day = max((d for d in pmc if d <= race_date), key=lambda d: pmc[d]["ctl"])
    print(f"\n  Szczyt CTL: {pmc[peak_ctl_day]['ctl']:.1f}  ({peak_ctl_day})")
    total_tss = sum(v["tss"] for v in pmc.values() if v["tss"] > 0)
    print(f"  Łączne TSS planu: {total_tss:.0f}\n")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Planowane TSS/CTL/ATL/TSB dla sezonu triathlonowego.")
    p.add_argument("--list",    action="store_true", help="Pokaż zapisane plany")
    p.add_argument("--prefix",  help="Prefix planu (np. WARSAW)")
    p.add_argument("--weeks",   type=int, help="Pokaż tylko ostatnie N tygodni")
    args = p.parse_args()

    if args.list:
        list_plans()
        return
    if not args.prefix:
        p.print_help()
        return

    state = load_state(args.prefix.upper())
    cfg   = state["config"]

    ftp          = cfg["ftp"]
    run_pace_ms  = cfg.get("run_pace_ms")
    race_date    = date.fromisoformat(cfg["race_date"])
    distance     = cfg["distance"]
    vol_scale    = cfg.get("vol_scale", 1.0)
    race_bike_pct = cfg.get("race_bike_pct")

    if not run_pace_ms and cfg.get("run_pace_str"):
        # Przelicz z MM:SS/km
        parts = cfg["run_pace_str"].split(":")
        run_pace_ms = 1000.0 / (int(parts[0]) * 60 + int(parts[1]))

    # Regeneruj plan (tylko lokalnie, bez logowania)
    try:
        from season_plan import generate_race_block
    except ImportError:
        sys.exit("BŁĄD: Brak pliku season_plan.py w bieżącym katalogu.")

    print(f"Obliczam obciążenie dla planu {args.prefix.upper()}...")
    all_wkts = generate_race_block(
        race_date, distance, ftp, run_pace_ms, args.prefix.upper(),
        race_bike_pct=race_bike_pct, vol_scale=vol_scale
    )

    # Szacuj TSS per trening
    daily_tss = {}
    workouts_by_date = {}
    for wkt, d in all_wkts:
        tss = estimate_tss(wkt, ftp, run_pace_ms)
        daily_tss[d] = daily_tss.get(d, 0.0) + tss
        workouts_by_date.setdefault(d, []).append(
            (wkt["workoutName"], wkt["sportType"]["sportTypeKey"], tss)
        )

    # Oblicz PMC od 6 tygodni przed planem (ctl/atl startuje z 0)
    plan_start = race_date - timedelta(weeks=int(cfg.get("distance") and
                 {"sprint":8,"olympic":10,"70.3":12,"full":16}[distance] or 12))
    pmc_start  = plan_start - timedelta(weeks=6)
    pmc        = compute_load(daily_tss, pmc_start, race_date)

    print_report(state, pmc, workouts_by_date, race_date, show_weeks=args.weeks)


if __name__ == "__main__":
    main()
