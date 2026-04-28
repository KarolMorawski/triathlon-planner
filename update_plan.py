#!/usr/bin/env python3
"""
update_plan.py — Aktualizacja istniejącego planu treningowego
=============================================================
Wczytuje zapisany stan planu (~/.triathlon_plans/{PREFIX}.json),
pokazuje postęp, przyjmuje nowe parametry (lub pobiera je ze Stravy)
i zastępuje przyszłe treningi zaktualizowanymi.

Użycie:
  python3 update_plan.py --list
  python3 update_plan.py --prefix WARSAW
  python3 update_plan.py --prefix WARSAW --ftp 265 --vol-scale 1.1
  python3 update_plan.py --prefix WARSAW --target-time 5:10:00
  python3 update_plan.py --prefix WARSAW --from-strava
  python3 update_plan.py --prefix WARSAW --from-strava --dry-run
  python3 update_plan.py --prefix WARSAW --from-date 2026-07-01 --ftp 270
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta

STATE_DIR = os.path.expanduser("~/.triathlon_plans")


# ─── STATE I/O ────────────────────────────────────────────────────────────────

def load_state(prefix):
    path = os.path.join(STATE_DIR, f"{prefix}.json")
    if not os.path.exists(path):
        sys.exit(
            f"BŁĄD: Brak zapisanego planu dla prefixu '{prefix}'\n"
            f"  Oczekiwano: {path}\n"
            f"  Uruchom najpierw season_plan.py lub generate_plan.py aby stworzyć plan."
        )
    with open(path) as f:
        return json.load(f)


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{state['prefix']}.json")
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  Stan zapisany → {path}")


# ─── LISTING ──────────────────────────────────────────────────────────────────

def list_plans():
    if not os.path.exists(STATE_DIR):
        print("Brak zapisanych planów.")
        return
    files = sorted(f for f in os.listdir(STATE_DIR) if f.endswith(".json"))
    if not files:
        print("Brak zapisanych planów.")
        return
    today = date.today()
    print(f"Zapisane plany ({STATE_DIR}):\n")
    for fname in files:
        try:
            with open(os.path.join(STATE_DIR, fname)) as fp:
                st = json.load(fp)
            cfg = st.get("config", {})
            wkts = st.get("workouts", [])
            done   = sum(1 for w in wkts if date.fromisoformat(w["date"]) < today)
            remain = len(wkts) - done
            updated = f"  zaktualizowany {st['updated_at']}" if st.get("updated_at") else ""
            print(f"  {st['prefix']:15s}  {cfg.get('race_date')}  {cfg.get('distance'):6s}  "
                  f"ftp={cfg.get('ftp')}W  "
                  f"wykonano={done}  pozostało={remain}  "
                  f"(generowany {st.get('generated_at')}{updated})")
        except Exception as e:
            print(f"  {fname}  [błąd odczytu: {e}]")


# ─── STATUS ───────────────────────────────────────────────────────────────────

def show_status(state, today=None):
    today = today or date.today()
    workouts = state.get("workouts", [])
    cfg = state["config"]

    def week_range(wlist):
        nums = set()
        for w in wlist:
            try:
                nums.add(int(w["name"].split("-T")[1][:2]))
            except (IndexError, ValueError):
                pass
        if not nums:
            return "—"
        lo, hi = min(nums), max(nums)
        return f"tydz. {lo}–{hi}" if lo != hi else f"tydz. {lo}"

    past   = [w for w in workouts if date.fromisoformat(w["date"]) < today]
    future = [w for w in workouts if date.fromisoformat(w["date"]) >= today]

    print(f"\n{'═'*55}")
    print(f"  PLAN: {state['prefix']}  ({cfg.get('race_date')}  {cfg.get('distance')})")
    print(f"{'═'*55}")
    print(f"  Generowany:   {state.get('generated_at')}")
    if state.get("updated_at"):
        print(f"  Zaktualizowany: {state['updated_at']}")
    print(f"  FTP:          {cfg.get('ftp')}W  |  Waga: {cfg.get('weight_kg')}kg")
    if cfg.get("target_time"):
        print(f"  Cel:          {cfg['target_time']}")
    if cfg.get("run_pace_str"):
        print(f"  Tempo biegu:  {cfg['run_pace_str']}/km")
    if cfg.get("vol_scale", 1.0) != 1.0:
        print(f"  Vol scale:    {cfg['vol_scale']}")
    print()

    if past:
        print(f"  Wykonano:   {len(past):3d} treningów  ({week_range(past)})")
    if future:
        print(f"  Pozostało:  {len(future):3d} treningów  ({week_range(future)})")
        nxt_date = min(w["date"] for w in future)
        nxt_name = next(w["name"] for w in future if w["date"] == nxt_date)
        print(f"  Następny:   {nxt_date}  {nxt_name}")
    elif not past:
        print("  Brak zapisanych treningów.")

    return past, future


# ─── GARMIN DELETE ────────────────────────────────────────────────────────────

def clean_future(client, state, cutoff):
    """Usuwa zaplanowania z kalendarza i treningi z biblioteki dla dat >= cutoff."""
    http = client.client
    prefix = state["prefix"]

    future_ids = {
        w["workout_id"] for w in state["workouts"]
        if w.get("workout_id") and date.fromisoformat(w["date"]) >= cutoff
    }
    if not future_ids:
        print("  Brak przyszłych treningów do usunięcia.")
        return

    # Usuń zaplanowania z kalendarza
    print(f"  Czyszczenie kalendarza od {cutoff}...")
    today = date.today()
    removed_s = 0
    for dm in range(0, 14):
        y = today.year + (today.month + dm - 1) // 12
        m = (today.month + dm - 1) % 12
        try:
            data = client.connectapi(f"/calendar-service/year/{y}/month/{m}")
            for item in data.get("calendarItems", []):
                if item.get("itemType") != "workout":
                    continue
                if not item.get("title", "").startswith(prefix):
                    continue
                raw = item.get("date") or item.get("startDate") or ""
                try:
                    if date.fromisoformat(raw[:10]) < cutoff:
                        continue
                except ValueError:
                    pass
                sid = item.get("id") or item.get("scheduleId")
                if sid:
                    try:
                        http.request("DELETE", "connectapi",
                                     f"/workout-service/schedule/{sid}", api=True)
                        removed_s += 1
                        time.sleep(0.08)
                    except Exception:
                        pass
        except Exception:
            pass
    print(f"    Usunięto {removed_s} zaplanowań")

    # Usuń treningi z biblioteki
    print(f"  Usuwanie {len(future_ids)} treningów z biblioteki...")
    removed_l = 0
    for wid in future_ids:
        try:
            http.request("DELETE", "connectapi",
                         f"/workout-service/workout/{wid}", api=True)
            removed_l += 1
            time.sleep(0.08)
        except Exception:
            pass
    print(f"    Usunięto {removed_l} treningów z biblioteki")


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _next_monday():
    today = date.today()
    days = (7 - today.weekday()) % 7 or 7
    return today + timedelta(days=days)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Aktualizacja planu treningowego triathlonu.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
przykłady:
  python3 update_plan.py --list
  python3 update_plan.py --prefix WARSAW
  python3 update_plan.py --prefix WARSAW --ftp 265 --vol-scale 1.1
  python3 update_plan.py --prefix WARSAW --target-time 5:10:00
  python3 update_plan.py --prefix WARSAW --from-strava
  python3 update_plan.py --prefix WARSAW --from-strava --dry-run
  python3 update_plan.py --prefix WARSAW --from-date 2026-07-14 --ftp 270
""")
    p.add_argument("--list",        action="store_true", help="Pokaż wszystkie zapisane plany")
    p.add_argument("--prefix",      help="Prefix planu do aktualizacji (np. WARSAW)")
    p.add_argument("--ftp",         type=int,   help="Nowe FTP w watach")
    p.add_argument("--run-pace",    help="Nowe tempo biegu MM:SS/km")
    p.add_argument("--target-time", help="Nowy planowany czas ukończenia H:MM:SS")
    p.add_argument("--vol-scale",   type=float, help="Nowy mnożnik objętości (0.5–1.5)")
    p.add_argument("--weight",      type=float, help="Nowa waga ciała kg")
    p.add_argument("--from-strava", action="store_true",
                   help="Pobierz sugestie ze Stravy przed aktualizacją")
    p.add_argument("--from-date",   help="Aktualizuj treningi od tej daty YYYY-MM-DD "
                                         "(domyślnie: następny poniedziałek)")
    p.add_argument("--dry-run",     action="store_true",
                   help="Podgląd zmian bez wgrywania do Garmin")
    args = p.parse_args()

    if args.list:
        list_plans()
        return

    if not args.prefix:
        p.print_help()
        return

    state = load_state(args.prefix.upper())
    today = date.today()
    past, future = show_status(state, today)

    if not future:
        print("\nBrak przyszłych treningów — plan zakończony lub wszystko w przeszłości.")
        return

    cfg = dict(state["config"])

    # Data graniczna aktualizacji
    cutoff = date.fromisoformat(args.from_date) if args.from_date else _next_monday()
    in_scope = [w for w in future if date.fromisoformat(w["date"]) >= cutoff]
    print(f"\n  Aktualizacja od: {cutoff}  ({len(in_scope)} treningów do zastąpienia)\n")

    # Sugestie ze Stravy
    if args.from_strava:
        try:
            from strava_suggest import _get_token, fetch_activities, analyze, suggest, print_report
            print("  Łączenie ze Stravą...")
            token = _get_token()
            acts  = fetch_activities(token, weeks=4)
            stats = analyze(acts, 4)
            sug   = suggest(cfg["distance"], stats)
            print_report(cfg["distance"], cfg.get("race_date"), 4, stats, sug)
            if args.vol_scale is None and sug.get("vol_scale"):
                args.vol_scale = sug["vol_scale"]
            if not args.target_time and sug.get("target_time"):
                args.target_time = sug["target_time"]
            # run_pace tylko jeśli nie mamy target_time
            if not args.run_pace and not args.target_time:
                rp = sug.get("run_pace_race", "—")
                if rp not in ("—", "", None):
                    args.run_pace = rp.replace("/km", "").strip()
        except Exception as e:
            print(f"  ⚠ Strava niedostępna: {e}")

    # Zastosuj nadpisania
    if args.ftp:                       cfg["ftp"]          = args.ftp
    if args.weight:                    cfg["weight_kg"]    = args.weight
    if args.vol_scale is not None:     cfg["vol_scale"]    = args.vol_scale
    if args.target_time:
        cfg["target_time"] = args.target_time
        cfg.pop("run_pace_str", None)
    elif args.run_pace:
        cfg["run_pace_str"] = args.run_pace
        cfg.pop("target_time", None)

    # Podsumowanie nowych parametrów
    print(f"  {'─'*50}")
    print(f"  Nowe parametry dla aktualizowanych tygodni:")
    print(f"    FTP:       {cfg['ftp']}W")
    print(f"    Vol scale: {cfg.get('vol_scale', 1.0)}")
    if cfg.get("target_time"):
        print(f"    Cel:       {cfg['target_time']}")
    elif cfg.get("run_pace_str"):
        print(f"    Tempo:     {cfg['run_pace_str']}/km")
    print(f"  {'─'*50}\n")

    # Import logiki generowania planu
    try:
        from season_plan import (generate_race_block, calc_splits,
                                  pace_to_ms, ms_to_pace, login, upload_workouts)
    except ImportError:
        sys.exit("BŁĄD: Brak pliku season_plan.py w bieżącym katalogu.")

    ftp       = cfg["ftp"]
    weight_kg = cfg.get("weight_kg", 75)
    cda       = cfg.get("cda", 0.32)
    vol_scale = cfg.get("vol_scale", 1.0)
    race_date = date.fromisoformat(cfg["race_date"])
    distance  = cfg["distance"]
    prefix    = state["prefix"]

    # Wyznacz tempo biegu i strefę rowerową
    race_bike_pct = None
    if cfg.get("target_time"):
        try:
            splits = calc_splits(distance, cfg["target_time"], ftp, weight_kg, cda)
            run_pace_ms   = splits["run_pace_ms"]
            race_bike_pct = splits["bike_pct_ftp"]
            cfg["run_pace_str"] = ms_to_pace(run_pace_ms)
            cfg["run_pace_ms"]  = run_pace_ms
            print(f"  Splity z {cfg['target_time']}:  "
                  f"bieg {splits['run_pace_str']}/km  "
                  f"rower ~{splits['bike_watts']}W ({splits['bike_pct_ftp']*100:.0f}% FTP)\n")
        except Exception as e:
            print(f"  ⚠ calc_splits: {e} — używam zapisanego tempa.")
            run_pace_ms = cfg.get("run_pace_ms") or pace_to_ms(cfg.get("run_pace_str", "5:30"))
    elif cfg.get("run_pace_str"):
        run_pace_ms = pace_to_ms(cfg["run_pace_str"])
        cfg["run_pace_ms"] = run_pace_ms
    else:
        sys.exit("BŁĄD: Brak tempa biegu lub czasu docelowego. Podaj --run-pace lub --target-time.")

    # Wygeneruj pełny plan, zachowaj tylko przyszłe treningi
    all_wkts  = generate_race_block(race_date, distance, ftp, run_pace_ms, prefix,
                                    race_bike_pct=race_bike_pct, vol_scale=vol_scale)
    new_wkts  = [(w, d) for w, d in all_wkts if date.fromisoformat(d) >= cutoff]

    print(f"  Treningi do wgrania: {len(new_wkts)}")

    # Predykcja TSB w dniu wyścigu
    try:
        from training_load import estimate_tss, compute_load
        import math
        from datetime import timedelta as _td
        daily_tss = {}
        for wkt, d in all_wkts:
            tss = estimate_tss(wkt, ftp, run_pace_ms)
            daily_tss[d] = daily_tss.get(d, 0.0) + tss
        _weeks = {"sprint": 8, "olympic": 10, "70.3": 12, "full": 16}
        plan_start = race_date - _td(weeks=_weeks.get(distance, 12))
        pmc_start  = plan_start - _td(weeks=6)
        pmc = compute_load(daily_tss, pmc_start, race_date)
        rp  = pmc.get(race_date, {})
        tsb, ctl = rp.get("tsb", 0), rp.get("ctl", 0)
        if tsb < 5:
            taper_date = (_next_monday() + _td(weeks=1)).isoformat()
            print(f"\n  ⚠ Prognoza TSB w dniu wyścigu: {tsb:+.1f}  CTL: {ctl:.0f}")
            print(f"    Za niskie (cel: 5–25). Rozważ dłuższy taper:")
            print(f"    uruchom z --from-date {taper_date} (tydzień wcześniej)\n")
        elif tsb > 25:
            taper_date = (_next_monday() - _td(weeks=1)).isoformat()
            print(f"\n  ⚠ Prognoza TSB w dniu wyścigu: {tsb:+.1f}  CTL: {ctl:.0f}")
            print(f"    Za wysokie (cel: 5–25). Rozważ krótszy taper:")
            print(f"    uruchom z --from-date {taper_date} (tydzień później)\n")
        else:
            print(f"\n  ✓ Prognoza TSB w dniu wyścigu: {tsb:+.1f}  CTL: {ctl:.0f}  — forma w normie\n")
    except Exception:
        pass

    if args.dry_run:
        print("\n  DRY RUN — podgląd przyszłych treningów po aktualizacji:\n")
        for wkt, d in sorted(new_wkts, key=lambda x: x[1]):
            sp = wkt["sportType"]["sportTypeKey"][0].upper()
            print(f"    {d}  [{sp}] {wkt['workoutName']}")
        print(f"\n  (Brak zmian — tryb podglądu)\n")
        return

    if not new_wkts:
        print("  Brak treningów do wgrania.")
        return

    confirm = input(
        f"\nUsunąć {len(in_scope)} istniejących przyszłych treningów "
        f"i wgrać {len(new_wkts)} nowych? (tak/nie): "
    ).strip().lower()
    if confirm not in ("tak", "t", "yes", "y"):
        print("Przerwano.")
        return

    print("\nLogowanie do Garmin Connect...")
    client = login()

    print(f"\nUsuwanie przyszłych treningów od {cutoff}...")
    clean_future(client, state, cutoff)

    print(f"\nWgrywanie {len(new_wkts)} treningów...")
    ok, fail, uploaded = upload_workouts(client, new_wkts)
    print(f"  ✓ Wgrano: {ok}" + (f" | Błędy: {fail}" if fail else ""))

    # Zachowaj przeszłość, zastąp przyszłość
    kept = [w for w in state["workouts"] if date.fromisoformat(w["date"]) < cutoff]
    state["workouts"]   = kept + uploaded
    state["config"]     = cfg
    state["updated_at"] = date.today().isoformat()

    save_state(state)
    print(f"\n  Plan zaktualizowany. Otwórz: https://connect.garmin.com/app/calendar\n")


if __name__ == "__main__":
    main()
