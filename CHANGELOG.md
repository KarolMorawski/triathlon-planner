# Changelog — Triathlon Training Planner

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.0] — 2026-04-03

### Pierwsza wersja produkcyjna

---

### Nowe funkcje

#### `generate_plan.py` — Generator planu dla jednych zawodów
- Interaktywny kreator lub uruchomienie z parametrami CLI
- Obsługiwane dystanse: `70.3`, `full`, `olympic`, `sprint`
- Parametry wejściowe: data wyścigu, dystans, FTP (W), tempo biegu (MM:SS/km), masa ciała, prefix
- Automatyczne obliczanie stref mocy (Z1–Z5 + Race pace) na podstawie FTP
- Automatyczne przeliczanie tempa biegu z formatu MM:SS/km na m/s (format Garmin API)
- Generowanie bloków: bieg + pływanie + rower z właściwymi intensywnościami per tydzień
- Flagi: `--reset`, `--dry-run`, `--config`
- Pełny reset: usuwa stare treningi z tym samym prefixem z kalendarza i biblioteki przed uploaden
- Upload i planowanie w kalendarzu Garmin w jednej operacji

#### `season_plan.py` — Generator planu sezonu (wiele zawodów)
- Obsługa wielu wyścigów w jednym pliku konfiguracyjnym JSON
- Każdy wyścig dostaje niezależny blok treningowy z własnym prefixem
- Plany nie kolidują ze sobą — `--reset` usuwa tylko treningi z danym prefixem
- Tryb interaktywny (sekwencyjne dodawanie zawodów) lub z pliku `season_example.json`
- Wykrywanie i ostrzeganie o nakładających się datach między blokami
- Podsumowanie sezonu przed uploadem z prośbą o potwierdzenie

#### `season_example.json` — Przykładowy plik konfiguracyjny sezonu
- Szablon JSON z polami: `ftp`, `run_pace`, `weight_kg`, `races[]`
- Każdy wyścig: `name` (prefix), `date` (YYYY-MM-DD), `distance`

#### `INSTRUKCJA.html` — Kompletna instrukcja instalacji
- Dedykowane zakładki dla Windows 10/11, macOS, Linux na każdym etapie
- Instalacja Python z ostrzeżeniem o "Add Python to PATH" (Windows)
- Instalacja Node.js (wymagane dla Strava MCP)
- Konfiguracja środowiska wirtualnego (venv) i bibliotek
- Strava MCP: konfiguracja `claude_desktop_config.json`, tworzenie aplikacji Strava API, autoryzacja OAuth
- Logowanie Garmin przez terminal: obsługa 2FA/MFA, problem z SSO (Google/Facebook login)
- Tabela komend dla obu paczek
- Sekcja rozwiązywania problemów (8 scenariuszy)

---

### Kluczowe odkrycia techniczne (Garmin API)

Udokumentowane przez analizę żądań sieciowych przeglądarki i testowanie empiryczne:

| Zagadnienie | Odkrycie |
|---|---|
| Power target (interwały) | `workoutTargetTypeId=2`, `workoutTargetTypeKey="power.zone"`, wartości w absolutnych watach |
| Power target (warmup/cooldown) | Musi być `workoutTargetTypeId=1` (`no.target`), wartości `null` |
| Błąd kph | `targetTypeId=5` lub power target na warmup/cooldown → Garmin wyświetla wartości jako m/s×3.6=kph |
| Pace target (bieg) | `workoutTargetTypeId=6`, `workoutTargetTypeKey="pace.zone"`, wartości w m/s |
| No target | `workoutTargetTypeId=1`, wartości `null` |
| Sport IDs | running=1, cycling=2, swimming=4 |
| garminconnect 0.3.x | Używa `self.client` zamiast `self.garth` — wykrywanie: `getattr(client, "garth", None) or getattr(client, "client", None)` |
| DELETE schedule | `http.request("DELETE", "connectapi", f"/workout-service/schedule/{sid}", api=True)` |
| DELETE workout | `http.request("DELETE", "connectapi", f"/workout-service/workout/{wid}", api=True)` |
| Kalendarz API | `GET /calendar-service/year/{year}/month/{0-indexed}` → `calendarItems` |
| Schedule vs Workout ID | Kalendarz przechowuje `scheduleId` (zaplanowanie) oddzielnie od `workoutId` (biblioteka) |

---

### Narzędzia i zależności

| Narzędzie | Wersja | Rola |
|---|---|---|
| Python | 3.10+ | Środowisko uruchomieniowe skryptów |
| garminconnect | 0.3.x | Komunikacja z Garmin Connect API |
| Node.js | 18+ LTS | Wymagane dla Strava MCP |
| @r-huijts/strava-mcp-server | latest (npx) | Strava MCP — analiza aktywności przez Claude |
| Claude Desktop | latest | Host dla MCP servers |

---

### Struktura plików

```
triathlon_single_race.zip
├── generate_plan.py       # generator planu dla jednych zawodów
└── INSTRUKCJA.html        # kompletna instrukcja

triathlon_season.zip
├── season_plan.py         # generator sezonu (wiele zawodów)
├── season_example.json    # przykładowy plik konfiguracyjny
├── generate_plan.py       # generator planu (jako moduł pomocniczy)
├── README.txt             # skrócona ściągawka
└── INSTRUKCJA.html        # kompletna instrukcja
```

---

### Znane ograniczenia v1.0.0

- Skrypty nie zapisują sesji Garmin — login wymagany przy każdym uruchomieniu
- Brak obsługi treningów z powtórzeniami (repeat groups) w Garmin
- Pliki .zwo dla MyWhoosh/Zwift generowane oddzielnie (poza tym zestawem)
- Nakładające się daty między blokami sezonowymi wymagają ręcznej korekty w Garmin

---

### Planowane w przyszłych wersjach

- [ ] Zapis tokenu sesji Garmin (logowanie raz, token ważny kilka godzin)
- [ ] Obsługa repeat groups (interwały z powtórzeniami w natywnym formacie Garmin)
- [ ] Generator plików .zwo zintegrowany z pakietem
- [ ] Eksport planu do formatu CSV / PDF
- [ ] Automatyczne wykrywanie FTP przez API Garmin/Strava
- [ ] SKILL.md dla Claude — skrócona dokumentacja API do użycia w nowych sesjach

