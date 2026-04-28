#!/usr/bin/env python3
"""
race_pacing_en.py — Race pacing calculator
==========================================
Given FTP and distance, shows three bike pacing scenarios
(conservative / target / aggressive) with predicted run degradation
and a nutrition plan.

No Garmin connection required.

Usage:
  python3 race_pacing_en.py --distance 70.3 --ftp 255 --weight 86
  python3 race_pacing_en.py --distance 70.3 --ftp 255 --weight 86 --target-time 5:00:00
  python3 race_pacing_en.py --distance full --ftp 255 --weight 86 --run-pace 5:20
"""

import argparse
import sys

DIST = {
    "sprint":  {"swim_m": 750,  "bike_km": 20,  "run_km": 5.0},
    "olympic": {"swim_m": 1500, "bike_km": 40,  "run_km": 10.0},
    "70.3":    {"swim_m": 1900, "bike_km": 90,  "run_km": 21.1},
    "full":    {"swim_m": 3800, "bike_km": 180, "run_km": 42.2},
}

RACE_IF = {"sprint": 0.95, "olympic": 0.88, "70.3": 0.82, "full": 0.72}

SWIM_MIN  = {"sprint": 12, "olympic": 22, "70.3": 35, "full": 75}
T1T2_MIN  = {"sprint": 3,  "olympic": 4,  "70.3": 5,  "full": 8}
BIKE_KG   = 8.0
RHO       = 1.225
CRR       = 0.004
ETA       = 0.975


# ─── BIKE PHYSICS ─────────────────────────────────────────────────────────────

def power_to_speed(watts, weight_kg, cda=0.32):
    """Returns speed [m/s] for a given power [W] on flat terrain."""
    m = weight_kg + BIKE_KG
    g = 9.81
    v = 10.0
    for _ in range(60):
        f  = (0.5 * RHO * cda * v**2 + CRR * m * g) * v / ETA - watts
        df = (1.5 * RHO * cda * v**2 + CRR * m * g) / ETA
        if df == 0:
            break
        delta = f / df
        v -= delta
        if abs(delta) < 1e-9:
            break
    return max(1.0, v)


# ─── RUN DEGRADATION MODEL ────────────────────────────────────────────────────

def run_degradation(if_val):
    """Fraction by which run pace slows after cycling at the given IF."""
    pts = [
        (0.65, 0.00), (0.70, 0.02), (0.75, 0.04),
        (0.80, 0.07), (0.85, 0.11), (0.90, 0.16), (1.00, 0.25),
    ]
    if if_val <= pts[0][0]:
        return 0.0
    if if_val >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x0 <= if_val < x1:
            t = (if_val - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return pts[-1][1]


# ─── NUTRITION ────────────────────────────────────────────────────────────────

def nutrition(bike_if, bike_min, run_min):
    """Returns (carb_bike_g, fluid_bike_ml, carb_run_g, fluid_run_ml)."""
    if   bike_if < 0.70: ch = 40
    elif bike_if < 0.80: ch = 55
    elif bike_if < 0.90: ch = 70
    else:                ch = 80

    bh = bike_min / 60
    rh = run_min  / 60
    return round(ch * bh), round(600 * bh), round(45 * rh), round(500 * rh)


# ─── FORMAT HELPERS ───────────────────────────────────────────────────────────

def _fmt_pace(ms):
    spk = 1000 / ms
    return f"{int(spk//60)}:{int(spk%60):02d}/km"

def _fmt_dur(minutes):
    h, m = divmod(int(round(minutes)), 60)
    return f"{h}:{m:02d}"

def _parse_pace(s):
    p = s.split(":")
    return 1000.0 / (int(p[0]) * 60 + int(p[1]))

def _parse_hms(s):
    p = s.strip().split(":")
    if len(p) == 3:
        return int(p[0]) * 60 + int(p[1]) + int(p[2]) / 60
    return int(p[0]) * 60 + int(p[1])


# ─── REPORT ───────────────────────────────────────────────────────────────────

def print_report(distance, ftp, weight_kg, cda, run_pace_fresh_ms, target_if):
    d = DIST[distance]
    bike_km  = d["bike_km"]
    run_km   = d["run_km"]
    swim_min = SWIM_MIN[distance]
    t1t2_min = T1T2_MIN[distance]

    scenarios = [
        ("Conservative", target_if - 0.04, ""),
        ("Target",       target_if,        " ← recommended"),
        ("Aggressive",   target_if + 0.04, ""),
    ]

    W = 62

    print(f"\n{'═'*W}")
    print(f"  RACE PACING — {distance.upper()}  |  FTP: {ftp}W  |  Weight: {weight_kg}kg")
    print(f"{'═'*W}")

    # ── Bike ──
    print(f"\n  BIKE SPLIT  ({bike_km} km)")
    print(f"  {'─'*58}")
    print(f"  {'Strategy':<18} {'Power':>8}  {'Speed':>8}  {'Time':>7}  IF")
    print(f"  {'─'*58}")

    bike_data = []
    for name, if_val, tag in scenarios:
        watts = if_val * ftp
        speed = power_to_speed(watts, weight_kg, cda)
        kmh   = speed * 3.6
        mins  = (bike_km * 1000 / speed) / 60
        bike_data.append((name, if_val, watts, kmh, mins, tag))
        print(f"  {name:<18} {round(watts):>5}W ({if_val*100:.0f}%)  "
              f"{kmh:>5.1f} km/h  {_fmt_dur(mins):>7}  {if_val:.2f}{tag}")

    # ── Run ──
    if run_pace_fresh_ms:
        print(f"\n  RUN PACE PREDICTION  ({run_km} km,  fresh pace: {_fmt_pace(run_pace_fresh_ms)})")
        print(f"  {'─'*58}")

        run_data = []
        for name, if_val, watts, kmh, bike_min, tag in bike_data:
            deg      = run_degradation(if_val)
            race_ms  = run_pace_fresh_ms / (1 + deg)
            run_min  = (run_km * 1000 / race_ms) / 60
            run_data.append((name, if_val, race_ms, run_min, bike_min))
            warn = "  ⚠ risky" if if_val > RACE_IF[distance] + 0.03 else ""
            print(f"  After {name.lower():<20} {_fmt_pace(race_ms):>9}  "
                  f"(–{deg*100:.0f}%)  →  {_fmt_dur(run_min)}{warn}")

        # ── Finish times ──
        print(f"\n  ESTIMATED FINISH TIMES  (swim: {_fmt_dur(swim_min)}, T1+T2: {_fmt_dur(t1t2_min)})")
        print(f"  {'─'*58}")
        for name, if_val, race_ms, run_min, bike_min in run_data:
            total = swim_min + t1t2_min + bike_min + run_min
            warn  = "  ⚠ risky" if if_val > RACE_IF[distance] + 0.03 else ""
            print(f"  {name:<18} {_fmt_dur(swim_min)} + {_fmt_dur(bike_min)} "
                  f"+ {_fmt_dur(t1t2_min)} + {_fmt_dur(run_min)} = {_fmt_dur(total)}{warn}")

        # ── Nutrition (target scenario) ──
        _, tgt_if, _, _, tgt_bike_min, _ = bike_data[1]
        _, _, tgt_run_ms, tgt_run_min, _ = run_data[1]
        cb, fb, cr, fr = nutrition(tgt_if, tgt_bike_min, tgt_run_min)

        print(f"\n  NUTRITION PLAN  (target scenario: {round(tgt_if*ftp)}W / {_fmt_dur(tgt_bike_min)})")
        print(f"  {'─'*58}")
        print(f"  Bike ({_fmt_dur(tgt_bike_min)}):")
        print(f"    Carbs:  {cb}g  ({cb/(tgt_bike_min/60):.0f}g/h)  — gels/bars every ~30 min")
        print(f"    Fluid:  {fb}ml  ({fb/(tgt_bike_min/60):.0f}ml/h) — isotonic bottles")
        print(f"  Run ({_fmt_dur(tgt_run_min)}):")
        print(f"    Carbs:  {cr}g  ({cr/(tgt_run_min/60):.0f}g/h)  — gels at aid stations")
        print(f"    Fluid:  {fr}ml  ({fr/(tgt_run_min/60):.0f}ml/h) — drink at every aid station")
        print(f"  {'─'*58}")
        print(f"  TOTAL: ~{cb+cr}g carbs  |  ~{fb+fr}ml fluid")
    else:
        print(f"\n  Provide --run-pace MM:SS or --target-time H:MM:SS")
        print(f"  to see run predictions and estimated finish times.")

    print()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Race pacing calculator — bike splits, run degradation, nutrition.")
    p.add_argument("--distance",    required=True, choices=list(DIST.keys()),
                   help="Race distance (sprint/olympic/70.3/full)")
    p.add_argument("--ftp",         required=True, type=int, help="FTP in watts")
    p.add_argument("--weight",      required=True, type=float, help="Body weight in kg")
    p.add_argument("--target-time", help="Target finish time H:MM:SS")
    p.add_argument("--run-pace",    help="Standalone (fresh) run pace MM:SS/km")
    p.add_argument("--cda",         type=float, default=0.32,
                   help="CdA in m² (default 0.32 — triathlon/TT position)")
    args = p.parse_args()

    run_pace_ms = None
    target_if   = RACE_IF[args.distance]

    if args.target_time:
        total_min = _parse_hms(args.target_time)
        swim_min  = SWIM_MIN[args.distance]
        t1t2_min  = T1T2_MIN[args.distance]
        d         = DIST[args.distance]
        active    = total_min - swim_min - t1t2_min

        ratios = {"sprint": (0.25, 0.75), "olympic": (0.30, 0.70),
                  "70.3":   (0.40, 0.60), "full":    (0.45, 0.55)}
        bike_frac, run_frac = ratios[args.distance]
        bike_min = active * bike_frac
        run_min  = active * run_frac

        run_pace_ms = (d["run_km"] * 1000) / (run_min * 60)
        bike_speed  = (d["bike_km"] * 1000) / (bike_min * 60)
        watts = (0.5 * RHO * args.cda * bike_speed**3 +
                 CRR * (args.weight + BIKE_KG) * 9.81 * bike_speed) / ETA
        target_if = watts / args.ftp

        print(f"\n  From target time {args.target_time}:")
        print(f"    Bike: ~{round(watts)}W ({target_if*100:.0f}% FTP) @ "
              f"{bike_speed*3.6:.1f} km/h  →  {_fmt_dur(bike_min)}")
        print(f"    Run:  {_fmt_pace(run_pace_ms)}/km  →  {_fmt_dur(run_min)}")

    elif args.run_pace:
        run_pace_ms = _parse_pace(args.run_pace)

    print_report(args.distance, args.ftp, args.weight, args.cda,
                 run_pace_ms, target_if)


if __name__ == "__main__":
    main()
