#!/usr/bin/env python3
"""
update_plan.py — Aktualizacja istniejącego planu treningowego
=============================================================
Wczytuje zapisany stan planu (~/.triathlon_plans/{PREFIX}.json),
pokazuje postęp, przyjmuje nowe parametry (lub pobiera je ze Stravy)
i zastępuje przyszłe treningi zaktualizowanymi.

Tryb pojedynczego wyścigu:
  python3 update_plan.py --list
  python3 update_plan.py --prefix WARSAW
  python3 update_plan.py --prefix WARSAW --ftp 265 --vol-scale 1.1
  python3 update_plan.py --prefix WARSAW --target-time 5:10:00
  python3 update_plan.py --prefix WARSAW --from-strava
  python3 update_plan.py --prefix WARSAW --from-date 2026-07-01 --ftp 270

Tryb całego sezonu (wspólne parametry dla wszystkich wyścigów z konfiga):
  python3 update_plan.py --config season.json
  python3 update_plan.py --config season.json --ftp 270 --vol-scale 1.1
  python3 update_plan.py --config season.json --from-strava
  python3 update_plan.py --config season.json --dry-run
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from triathlon_core import (
    STATE_DIR,
    validate_prefix_pl as _validate_prefix,
    load_state_pl as load_state,
)


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


def _state_exists(prefix):
    return os.path.exists(os.path.join(STATE_DIR, f"{prefix}.json"))


# ─── PER-RACE PLANNING ────────────────────────────────────────────────────────

def _apply_strava_to_args(args, distance, strava_stats):
    """Apply Strava suggestions to args (in place) for given distance."""
    try:
        from strava_suggest import suggest, print_report
    except ImportError as e:
        print(f"  ⚠ Strava niedostępna: {e}")
        return
    sug = suggest(distance, strava_stats)
    print_report(distance, None, 4, strava_stats, sug)
    if args.vol_scale is None and sug.get("vol_scale"):
        args.vol_scale = sug["vol_scale"]
    if not args.target_time and sug.get("target_time"):
        args.target_time = sug["target_time"]
    if not args.run_pace and not args.target_time:
        rp = sug.get("run_pace_race", "—")
        if rp not in ("—", "", None):
            args.run_pace = rp.replace("/km", "").strip()


def _plan_race_update(prefix, args, today, strava_stats=None):
    """
    Plan an update for one race. Returns dict with plan data, or None if skipped.
    Mutates a copy of args for race-specific Strava overrides.
    """
    state = load_state(prefix)
    show_status(state, today)

    workouts = state.get("workouts", [])
    future = [w for w in workouts if date.fromisoformat(w["date"]) >= today]
    if not future:
        print(f"  [{prefix}] Brak przyszłych treningów — pomijam.\n")
        return None

    cfg = dict(state["config"])
    distance = cfg["distance"]

    # Race-local args copy so per-race Strava suggestions don't leak across races
    import copy
    local_args = copy.copy(args)

    # Strava: per-race suggest() based on distance
    if args.from_strava and strava_stats is not None:
        _apply_strava_to_args(local_args, distance, strava_stats)

    cutoff = date.fromisoformat(local_args.from_date) if local_args.from_date else _next_monday()
    in_scope = [w for w in future if date.fromisoformat(w["date"]) >= cutoff]
    print(f"  [{prefix}] Aktualizacja od: {cutoff}  ({len(in_scope)} treningów do zastąpienia)\n")

    # Apply CLI overrides
    if local_args.ftp:                      cfg["ftp"]       = local_args.ftp
    if local_args.weight:                   cfg["weight_kg"] = local_args.weight
    if local_args.vol_scale is not None:    cfg["vol_scale"] = local_args.vol_scale
    if local_args.target_time:
        cfg["target_time"] = local_args.target_time
        cfg.pop("run_pace_str", None)
    elif local_args.run_pace:
        cfg["run_pace_str"] = local_args.run_pace
        cfg.pop("target_time", None)

    print(f"  [{prefix}] Nowe parametry:  FTP={cfg['ftp']}W  vol={cfg.get('vol_scale', 1.0)}"
          + (f"  cel={cfg['target_time']}" if cfg.get("target_time")
             else f"  tempo={cfg.get('run_pace_str','—')}/km"))

    # Resolve run pace + bike zone
    try:
        from season_plan import (generate_race_block, calc_splits,
                                  pace_to_ms, ms_to_pace)
    except ImportError:
        sys.exit("BŁĄD: Brak pliku season_plan.py w bieżącym katalogu.")

    ftp       = cfg["ftp"]
    weight_kg = cfg.get("weight_kg", 75)
    cda       = cfg.get("cda", 0.32)
    vol_scale = cfg.get("vol_scale", 1.0)
    race_date = date.fromisoformat(cfg["race_date"])

    race_bike_pct = None
    if cfg.get("target_time"):
        try:
            splits = calc_splits(distance, cfg["target_time"], ftp, weight_kg, cda)
            run_pace_ms   = splits["run_pace_ms"]
            race_bike_pct = splits["bike_pct_ftp"]
            cfg["run_pace_str"] = ms_to_pace(run_pace_ms)
            cfg["run_pace_ms"]  = run_pace_ms
            print(f"  [{prefix}] Splity z {cfg['target_time']}:  "
                  f"bieg {splits['run_pace_str']}/km  "
                  f"rower ~{splits['bike_watts']}W ({splits['bike_pct_ftp']*100:.0f}% FTP)")
        except Exception as e:
            print(f"  [{prefix}] ⚠ calc_splits: {e} — używam zapisanego tempa.")
            run_pace_ms = cfg.get("run_pace_ms") or pace_to_ms(cfg.get("run_pace_str", "5:30"))
    elif cfg.get("run_pace_str"):
        run_pace_ms = pace_to_ms(cfg["run_pace_str"])
        cfg["run_pace_ms"] = run_pace_ms
    else:
        sys.exit(f"BŁĄD: [{prefix}] Brak tempa biegu lub czasu docelowego.")

    all_wkts = generate_race_block(race_date, distance, ftp, run_pace_ms, prefix,
                                   race_bike_pct=race_bike_pct, vol_scale=vol_scale)
    new_wkts = [(w, d) for w, d in all_wkts if date.fromisoformat(d) >= cutoff]

    print(f"  [{prefix}] Treningi do wgrania: {len(new_wkts)}\n")

    return {
        "prefix":      prefix,
        "state":       state,
        "cfg":         cfg,
        "cutoff":      cutoff,
        "in_scope":    in_scope,
        "all_wkts":    all_wkts,
        "new_wkts":    new_wkts,
        "ftp":         ftp,
        "run_pace_ms": run_pace_ms,
        "race_date":   race_date,
        "distance":    distance,
    }


def _predict_tsb(plan_data):
    """Print TSB prediction for race day. Skipped silently if training_load.py absent."""
    try:
        from training_load import estimate_tss, compute_load
    except ImportError:
        return
    daily_tss = {}
    for wkt, d in plan_data["all_wkts"]:
        tss = estimate_tss(wkt, plan_data["ftp"], plan_data["run_pace_ms"])
        daily_tss[d] = daily_tss.get(d, 0.0) + tss
    _weeks = {"sprint": 8, "olympic": 10, "70.3": 12, "full": 16}
    plan_start = plan_data["race_date"] - timedelta(weeks=_weeks[plan_data["distance"]])
    pmc_start  = plan_start - timedelta(weeks=6)
    pmc = compute_load(daily_tss, pmc_start, plan_data["race_date"])
    rp  = pmc.get(plan_data["race_date"], {})
    tsb, ctl = rp.get("tsb", 0), rp.get("ctl", 0)
    pfx = plan_data["prefix"]
    if tsb < 5:
        taper_date = (_next_monday() + timedelta(weeks=1)).isoformat()
        print(f"  [{pfx}] ⚠ TSB w dniu wyścigu: {tsb:+.1f}  CTL: {ctl:.0f} — za niski (cel: 5–25).")
        print(f"  [{pfx}]   Sugestia: --from-date {taper_date} (tydzień wcześniej, dłuższy taper)\n")
    elif tsb > 25:
        taper_date = (_next_monday() - timedelta(weeks=1)).isoformat()
        print(f"  [{pfx}] ⚠ TSB w dniu wyścigu: {tsb:+.1f}  CTL: {ctl:.0f} — za wysoki (cel: 5–25).")
        print(f"  [{pfx}]   Sugestia: --from-date {taper_date} (tydzień później, krótszy taper)\n")
    else:
        print(f"  [{pfx}] ✓ TSB w dniu wyścigu: {tsb:+.1f}  CTL: {ctl:.0f} — forma w normie\n")


def _execute_upload(client, plan_data):
    """Run clean_future + upload + save_state for one race."""
    try:
        from season_plan import upload_workouts
    except ImportError:
        sys.exit("BŁĄD: Brak pliku season_plan.py w bieżącym katalogu.")

    pfx = plan_data["prefix"]
    print(f"\n[{pfx}] Usuwanie przyszłych treningów od {plan_data['cutoff']}...")
    clean_future(client, plan_data["state"], plan_data["cutoff"])

    print(f"[{pfx}] Wgrywanie {len(plan_data['new_wkts'])} treningów...")
    ok, fail, uploaded = upload_workouts(client, plan_data["new_wkts"])
    print(f"  ✓ Wgrano: {ok}" + (f" | Błędy: {fail}" if fail else ""))

    state = plan_data["state"]
    cutoff = plan_data["cutoff"]
    kept = [w for w in state["workouts"] if date.fromisoformat(w["date"]) < cutoff]
    state["workouts"]   = kept + uploaded
    state["config"]     = plan_data["cfg"]
    state["updated_at"] = date.today().isoformat()
    save_state(state)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Aktualizacja planu treningowego triathlonu (pojedynczy wyścig lub cały sezon).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
przykłady:
  # Pojedynczy wyścig
  python3 update_plan.py --list
  python3 update_plan.py --prefix WARSAW --ftp 265 --vol-scale 1.1
  python3 update_plan.py --prefix WARSAW --target-time 5:10:00
  python3 update_plan.py --prefix WARSAW --from-strava

  # Cały sezon (te same parametry dla wszystkich wyścigów z konfiga)
  python3 update_plan.py --config season.json --ftp 270
  python3 update_plan.py --config season.json --vol-scale 1.1 --from-strava
  python3 update_plan.py --config season.json --dry-run
""")
    p.add_argument("--list",        action="store_true", help="Pokaż wszystkie zapisane plany")
    p.add_argument("--prefix",      help="Prefix planu do aktualizacji (np. WARSAW)")
    p.add_argument("--config",      help="Plik konfiguracyjny sezonu — aktualizuje wszystkie wyścigi")
    p.add_argument("--ftp",         type=int,   help="Nowe FTP w watach")
    p.add_argument("--run-pace",    help="Nowe tempo biegu MM:SS/km")
    p.add_argument("--target-time", help="Nowy planowany czas ukończenia H:MM:SS (tylko --prefix)")
    p.add_argument("--vol-scale",   type=float, help="Nowy mnożnik objętości (0.5–1.5)")
    p.add_argument("--weight",      type=float, help="Nowa waga ciała kg")
    p.add_argument("--from-strava", action="store_true",
                   help="Pobierz sugestie ze Stravy przed aktualizacją")
    p.add_argument("--from-date",   help="Aktualizuj treningi od tej daty YYYY-MM-DD "
                                         "(domyślnie: następny poniedziałek)")
    p.add_argument("--dry-run",     action="store_true",
                   help="Podgląd zmian bez wgrywania do Garmin")
    args = p.parse_args()

    if args.ftp is not None and args.ftp <= 0:
        p.error(f"--ftp must be > 0 (got {args.ftp})")
    if args.weight is not None and args.weight <= 0:
        p.error(f"--weight must be > 0 (got {args.weight})")
    if args.vol_scale is not None and not (0.1 <= args.vol_scale <= 3.0):
        p.error(f"--vol-scale must be in [0.1, 3.0] (got {args.vol_scale})")

    if args.list:
        list_plans()
        return

    if args.config and args.prefix:
        p.error("użyj --config LUB --prefix, nie obu naraz")
    if args.config and args.target_time:
        p.error("--target-time działa tylko z --prefix (każdy wyścig ma własny cel)")
    if not args.config and not args.prefix:
        p.print_help()
        return

    today = date.today()

    # Build prefix list
    if args.config:
        try:
            with open(args.config) as f:
                cfg_season = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            sys.exit(f"BŁĄD: Nie można odczytać konfiga '{args.config}': {e}")
        try:
            from season_plan import _validate_config
            _validate_config(cfg_season, args.config)
        except ImportError:
            sys.exit("BŁĄD: Brak pliku season_plan.py w bieżącym katalogu.")
        prefixes = [r["name"].upper() for r in cfg_season["races"]]
    else:
        prefixes = [args.prefix.upper()]

    for prefix in prefixes:
        _validate_prefix(prefix)

    # Strava: fetch + analyze ONCE, suggest per race
    strava_stats = None
    if args.from_strava:
        try:
            from strava_suggest import _get_token, fetch_activities, analyze
            print("Łączenie ze Stravą...")
            token = _get_token()
            acts  = fetch_activities(token, weeks=4)
            strava_stats = analyze(acts, 4)
        except Exception as e:
            print(f"  ⚠ Strava niedostępna: {e}\n")

    # Plan each race
    plans   = []
    skipped = []
    for prefix in prefixes:
        if not _state_exists(prefix):
            skipped.append((prefix, "brak zapisanego stanu — uruchom najpierw season_plan/generate_plan"))
            continue
        plan_data = _plan_race_update(prefix, args, today, strava_stats)
        if plan_data is None:
            skipped.append((prefix, "brak przyszłych treningów"))
            continue
        plans.append(plan_data)

    if skipped:
        print(f"{'─'*55}")
        print("Pominięte:")
        for pfx, why in skipped:
            print(f"  {pfx:15s}  {why}")
        print()

    if not plans:
        print("Nic do aktualizacji.")
        return

    # TSB per race
    print(f"{'─'*55}")
    print("Prognoza formy:")
    for plan_data in plans:
        _predict_tsb(plan_data)

    # Season summary
    if len(plans) > 1:
        print(f"{'─'*55}")
        print(f"Podsumowanie sezonu ({len(plans)} wyścigów):")
        for pd_ in plans:
            print(f"  {pd_['prefix']:15s}  {pd_['cfg']['race_date']}  "
                  f"{pd_['distance']:6s}  do wgrania: {len(pd_['new_wkts']):3d}  "
                  f"do usunięcia: {len(pd_['in_scope']):3d}")
        print()

    if args.dry_run:
        print(f"{'─'*55}")
        print("DRY RUN — pierwsze 10 treningów per wyścig:\n")
        for plan_data in plans:
            print(f"[{plan_data['prefix']}]")
            for wkt, d in sorted(plan_data["new_wkts"], key=lambda x: x[1])[:10]:
                sp = wkt["sportType"]["sportTypeKey"][0].upper()
                print(f"    {d}  [{sp}] {wkt['workoutName']}")
            if len(plan_data["new_wkts"]) > 10:
                print(f"    ... ({len(plan_data['new_wkts']) - 10} więcej)")
            print()
        print("(Brak zmian — tryb podglądu)\n")
        return

    total_new      = sum(len(p["new_wkts"]) for p in plans)
    total_in_scope = sum(len(p["in_scope"]) for p in plans)
    label = f"{len(plans)} wyścigów" if len(plans) > 1 else plans[0]["prefix"]
    confirm = input(
        f"\nUsunąć {total_in_scope} istniejących i wgrać {total_new} nowych "
        f"treningów ({label})? (tak/nie): "
    ).strip().lower()
    if confirm not in ("tak", "t", "yes", "y"):
        print("Przerwano.")
        return

    print("\nLogowanie do Garmin Connect...")
    try:
        from season_plan import login
    except ImportError:
        sys.exit("BŁĄD: Brak pliku season_plan.py w bieżącym katalogu.")
    client = login()

    for plan_data in plans:
        _execute_upload(client, plan_data)

    print(f"\n{'─'*55}")
    print(f"Zaktualizowano {len(plans)} wyścig(ów). Otwórz: https://connect.garmin.com/app/calendar\n")


if __name__ == "__main__":
    main()
