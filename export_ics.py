#!/usr/bin/env python3
"""
export_ics.py — Eksport planu do kalendarza (.ics)
===================================================
Generuje plik iCalendar ze wszystkimi zaplanowanymi treningami.
Plik można zaimportować do Google Calendar, Apple Calendar lub Outlooka.

Wymaga zapisanego stanu planu (~/.triathlon_plans/{PREFIX}.json).

Użycie:
  python3 export_ics.py --prefix WARSAW
  python3 export_ics.py --prefix WARSAW --output moj_plan.ics
  python3 export_ics.py --prefix WARSAW --future-only
  python3 export_ics.py --list
"""

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta

STATE_DIR = os.path.expanduser("~/.triathlon_plans")

_PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")

def _validate_prefix(p):
    """Reject prefixes that could escape STATE_DIR or contain unsafe characters."""
    if not _PREFIX_RE.match(p):
        sys.exit(f"BŁĄD: Niepoprawny prefix '{p}'. Dozwolone: A-Z, 0-9, _, - (musi zaczynać się od znaku alfanumerycznego).")

SPORT_ICON = {"running": "🏃", "cycling": "🚲", "swimming": "🏊"}
SPORT_PL   = {"running": "Bieg", "cycling": "Rower", "swimming": "Pływanie"}

# Szacowany czas trwania sesji [minuty] — do ustawienia DTEND
SPORT_DUR  = {"running": 75, "cycling": 90, "swimming": 60}


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
            print(f"  {st['prefix']:15s}  {cfg.get('race_date')}  "
                  f"{cfg.get('distance'):6s}  wykonano={done}/{len(wkts)}")
        except Exception:
            pass


# ─── ICS ──────────────────────────────────────────────────────────────────────

def _esc(s):
    """Escapuje znaki specjalne w tekście ICS."""
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_date(d):
    return d.strftime("%Y%m%d")


def _fold(line, limit=74):
    """RFC 5545 line folding — split lines >75 octets, respecting UTF-8 boundaries."""
    encoded = line.encode("utf-8")
    if len(encoded) <= limit + 1:
        return line
    chunks = []
    pos = 0
    while pos < len(encoded):
        end = min(pos + limit, len(encoded))
        # Don't split a multi-byte UTF-8 sequence: walk back to code-point boundary
        while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(encoded[pos:end].decode("utf-8"))
        pos = end
    return "\r\n ".join(chunks)


def generate_ics(state, workouts, prefix):
    """Zwraca treść pliku ICS jako string."""
    cfg = state["config"]
    race_date = date.fromisoformat(cfg["race_date"])

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//Triathlon Planner//{prefix}//PL",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:" + _esc(f"Triatlon — {prefix}"),
        "X-WR-CALDESC:" + _esc(
            f"Plan treningowy {cfg.get('distance','').upper()} · "
            f"wyścig {cfg.get('race_date')} · FTP {cfg.get('ftp')}W"
        ),
    ]

    for wkt, d_str in sorted(workouts, key=lambda x: x[1]):
        d_obj  = date.fromisoformat(d_str)
        sport  = wkt["sportType"]["sportTypeKey"]
        name   = wkt["workoutName"]
        icon   = SPORT_ICON.get(sport, "●")
        sport_pl = SPORT_PL.get(sport, sport)
        dur_min  = SPORT_DUR.get(sport, 60)

        # Wszystkie treningi jako całodniowe (no specific time)
        dtstart = _ics_date(d_obj)
        dtend   = _ics_date(d_obj + timedelta(days=1))

        uid = f"{prefix}-{d_str}-{sport[:3].upper()}@triathlon-planner"

        # Opis: podsumowanie sesji z podstawowych parametrów
        desc_parts = [sport_pl]
        cfg_ = state["config"]
        if sport == "cycling" and cfg_.get("ftp"):
            ftp = cfg_["ftp"]
            desc_parts.append(f"FTP: {ftp}W")
        elif sport == "running" and cfg_.get("run_pace_str"):
            desc_parts.append(f"Tempo: {cfg_['run_pace_str']}/km")
        if d_obj == race_date:
            desc_parts.append("DZIEŃ WYŚCIGU 🏁")

        description = " · ".join(desc_parts)

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;VALUE=DATE:{dtstart}",
            f"DTEND;VALUE=DATE:{dtend}",
            f"SUMMARY:{icon} {_esc(name)}",
            f"DESCRIPTION:{_esc(description)}",
            f"CATEGORIES:{sport_pl.upper()}",
            "END:VEVENT",
        ]

    # Wydarzenie wyścigu
    lines += [
        "BEGIN:VEVENT",
        f"UID:{prefix}-RACE-{cfg['race_date']}@triathlon-planner",
        f"DTSTART;VALUE=DATE:{_ics_date(race_date)}",
        f"DTEND;VALUE=DATE:{_ics_date(race_date + timedelta(days=1))}",
        f"SUMMARY:🏁 WYŚCIG — {prefix} ({cfg.get('distance','').upper()})",
        "DESCRIPTION:" + _esc(f"Cel: {cfg.get('target_time','—')}  FTP: {cfg.get('ftp')}W"),
        "CATEGORIES:WYŚCIG",
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    return "\r\n".join(_fold(l) for l in lines)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Eksport planu treningowego do pliku .ics (Google/Apple/Outlook).")
    p.add_argument("--list",        action="store_true", help="Pokaż zapisane plany")
    p.add_argument("--prefix",      help="Prefix planu (np. WARSAW)")
    p.add_argument("--output",      help="Nazwa pliku wyjściowego (domyślnie: {PREFIX}.ics)")
    p.add_argument("--future-only", action="store_true",
                   help="Eksportuj tylko przyszłe treningi")
    args = p.parse_args()

    if args.list:
        list_plans()
        return
    if not args.prefix:
        p.print_help()
        return

    prefix_arg = args.prefix.upper()
    _validate_prefix(prefix_arg)
    state  = load_state(prefix_arg)
    cfg    = state["config"]
    prefix = state["prefix"]

    ftp          = cfg["ftp"]
    run_pace_ms  = cfg.get("run_pace_ms")
    race_date    = date.fromisoformat(cfg["race_date"])
    distance     = cfg["distance"]
    vol_scale    = cfg.get("vol_scale", 1.0)
    race_bike_pct = cfg.get("race_bike_pct")

    if not run_pace_ms and cfg.get("run_pace_str"):
        parts = cfg["run_pace_str"].split(":")
        run_pace_ms = 1000.0 / (int(parts[0]) * 60 + int(parts[1]))

    try:
        from season_plan import generate_race_block
    except ImportError:
        sys.exit("BŁĄD: Brak pliku season_plan.py w bieżącym katalogu.")

    print(f"Generowanie planu {prefix}...")
    all_wkts = generate_race_block(
        race_date, distance, ftp, run_pace_ms, prefix,
        race_bike_pct=race_bike_pct, vol_scale=vol_scale
    )

    today = date.today()
    if args.future_only:
        workouts = [(w, d) for w, d in all_wkts if date.fromisoformat(d) >= today]
        print(f"Eksportowane: {len(workouts)} przyszłych treningów")
    else:
        workouts = all_wkts
        print(f"Eksportowane: {len(workouts)} treningów (cały plan)")

    ics_content = generate_ics(state, workouts, prefix)

    out_path = args.output or f"{prefix}.ics"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(ics_content)

    print(f"\n  ✓ Zapisano: {out_path}  ({len(workouts)} treningów)\n")
    print(f"  Import do kalendarza:")
    print(f"    Google Calendar:  calendar.google.com → Inne kalendarze → Import")
    print(f"    Apple Calendar:   Plik → Importuj → wybierz {out_path}")
    print(f"    Outlook:          Plik → Otwórz i eksportuj → Importuj/eksportuj\n")


if __name__ == "__main__":
    main()
