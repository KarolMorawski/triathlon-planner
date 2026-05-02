# Changelog — Triathlon Training Planner

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.13.1] — 2026-05-02

### Fixed

- `season_plan.py`, `season_plan_en.py`, `generate_plan.py`, `generate_plan_en.py`: replaced deprecated `client.save_workout()` with `client.upload_workout()` — garminconnect 0.3.x renamed this method, causing all workout uploads to fail with `AttributeError`

---

## [1.13.0] — 2026-04-29

### Changed

#### `INSTRUKCJA.html` — full documentation overhaul

- Added sections 12 (MyWhoosh/Zwift .zwo) and 13 (Strava Suggest) — previously undocumented tools
- Documented all missing CLI options: `--auto-ftp`, `--target-time`, `--weight`, `--cda`, `--prefix`, `--vol-scale` in `generate_plan.py`; `--ftp`, `--auto-ftp`, `--run-pace`, `--vol-scale` in `season_plan.py`; `--config`, `--run-pace`, `--weight` in `update_plan.py`; `--list` in `training_load.py`; `--cda` in `race_pacing.py`
- Fixed incorrect Garmin login description — section 5 now correctly documents OAuth token caching (`~/.garmin_token`), shared across all scripts
- Added troubleshooting entry for "No saved plan for PREFIX" (dry-run does not save state)
- Added token refresh/reset instructions (Windows and Mac/Linux)
- Added note about English versions (`*_en.py`) in header and section 0
- Updated TOC to include sections 12 and 13

---

## [1.12.0] — 2026-04-28

### Added

#### `update_plan.py --config season.json` — whole-season update

Rebuild the upcoming weeks of every race in a season config in one pass.

- Same `--ftp`, `--vol-scale`, `--weight`, `--run-pace`, `--from-date`,
  `--from-strava`, `--dry-run` flags now apply to all races.
- Strava data is fetched **once** per run; `suggest()` still runs per race
  because volume targets depend on distance.
- Single confirmation prompt and single Garmin login for the whole batch.
- Races without a saved state file are listed as "skipped"; the rest proceed.
- `--target-time` is rejected with `--config` (each race has its own target);
  use single-race mode (`--prefix`) for race-specific target overrides.
- Per-race TSB prediction is printed for every race in the batch.

```bash
python3 update_plan.py --config season.json --ftp 270 --vol-scale 1.1
python3 update_plan_en.py --config season.json --from-strava --dry-run
```

Single-race mode (`--prefix`) keeps the same UX. Internally the per-race logic
was extracted into `_plan_race_update()`, `_predict_tsb()` and
`_execute_upload()` so both modes share the same code path.

---

## [1.11.1] — 2026-04-28

### Security

- **OAuth token file now written with `0o600` permissions** (`~/.garmin_token`).
  On multi-user systems the previous default umask left the token world-readable,
  allowing other accounts on the same machine to steal the Garmin session.
  Token I/O switched to context managers (closes a small file-handle leak).

- **Plan prefix is now validated** against `^[A-Z0-9][A-Z0-9_-]*$` at every
  entry point that opens a state file. Rejects `--prefix '../foo'` and similar
  attempts to read or overwrite arbitrary paths outside `~/.triathlon_plans/`.

- **Season config (JSON) is now schema-validated** before use. Malformed JSON
  or missing required fields (`races`, `distance`, `date`) produce a clear
  one-line error instead of a deep traceback.

### Fixed

- Negative or zero `--ftp`, `--weight`, `--cda` and out-of-range `--vol-scale`
  are now rejected at the CLI with a clear message. Previously they propagated
  into physics calculations and produced nonsense or `ZeroDivisionError`.
- `update_plan.py` TSB prediction no longer swallows `Exception` blanket-style.
  Only the optional `training_load` import failure is caught; any computation
  error surfaces normally so it can be diagnosed.
- Polish typo in `race_pacing.py` nutrition output: `punkatch` → `punktach`.
- `power_to_speed()` (Newton's method) now warns to stderr when it fails to
  converge in 60 iterations instead of silently returning a wrong speed.
- ICS files now fold lines longer than 75 octets per RFC 5545. Long workout
  names with Polish characters and emoji previously broke strict iCalendar
  parsers (Thunderbird, some Google Calendar paths). Fold respects UTF-8
  multi-byte boundaries.

---

## [1.11.0] — 2026-04-28

### Added

#### `race_pacing.py` / `race_pacing_en.py` — race pacing calculator

Standalone tool, no Garmin login required.

- Three bike scenarios (conservative/target/aggressive) at race IF ±4%
- Bike physics model (Newton's method, flat course): power → speed → split time
- Run degradation model: piecewise linear, IF 0.65–1.00 → 0–25% slowdown
- Estimated finish time for each scenario
- Nutrition plan for the target scenario (carbs g/h + fluid ml/h per leg)
- If `--target-time` given: derives target IF and run pace from splits
- If `--run-pace` given: uses distance profile default IF

```bash
python3 race_pacing_en.py --distance 70.3 --ftp 255 --weight 86
python3 race_pacing_en.py --distance 70.3 --ftp 255 --weight 86 --target-time 5:00:00
```

#### `export_ics.py` / `export_ics_en.py` — iCalendar export

- Generates `.ics` from saved plan state (requires `~/.triathlon_plans/{PREFIX}.json`)
- Each workout = all-day VEVENT (DTSTART/DTEND VALUE=DATE)
- Race day marked as a separate event with target time in description
- `--future-only` to export only upcoming workouts
- Import instructions printed after generation

```bash
python3 export_ics_en.py --prefix WARSAW --future-only
```

#### TSB prediction in `update_plan.py` / `update_plan_en.py`

- After generating the updated plan, computes predicted race day TSB/CTL
  using the same PMC model as `training_load.py` (imports `estimate_tss`, `compute_load`)
- TSB 5–25 → "on target"; outside range → specific `--from-date` suggestion
- Wrapped in try/except so missing `training_load.py` is silently skipped

---

## [1.10.0] — 2026-04-28

### Added

#### `training_load.py` / `training_load_en.py` — training load estimation (TSS/CTL/ATL/TSB)

New offline module — no Garmin login required.

- Regenerates full workout structure from saved plan state
- Estimates TSS per session: bike (NP method), run (rTSS), swim (50 TSS/h)
- Computes PMC curves: CTL (fitness, TC=42d), ATL (fatigue, TC=7d), TSB (form = CTL−ATL)
- Weekly bar chart with taper/race-week markers
- Race-day form assessment: TSB 5–25 = good; outside range → taper advice
- CLI: `--prefix WARSAW`, `--weeks 4`, `--list`

#### `plan_review.py` / `plan_review_en.py` — planned vs actual comparison

- Logs in to Garmin Connect and fetches activity history
- Matches activities to planned workouts by (date, sport)
- GARMIN_SPORT mapping handles type variants (road_cycling, trail_running, virtual_ride, etc.)
- Shows ✓ with actual duration/power/pace or ✗ missed per session
- Weekly completion bar and overall percentage
- CLI: `--prefix WARSAW`, `--weeks 4`, `--list`

#### `--auto-ftp` flag in all 4 planner scripts

Added to `season_plan.py`, `season_plan_en.py`, `generate_plan.py`, `generate_plan_en.py`.

- Reads FTP automatically from Garmin Connect (`/userprofile-service/userprofile/cycle-power-metrics`)
- Graceful fallback to config/manual value if endpoint unavailable
- Skipped if `--ftp` is provided explicitly

```bash
python3 generate_plan_en.py --race-date 2026-09-15 --distance 70.3 --auto-ftp --run-pace 5:20
python3 season_plan_en.py --config season.json --auto-ftp
```

---

## [1.9.0] — 2026-04-28

### Dodane

#### `update_plan.py` / `update_plan_en.py` — aktualizacja istniejącego planu

Nowy moduł do rekalibracji planu w trakcie sezonu (np. po 2 miesiącach treningu).

- `update_plan.py --list` — lista wszystkich zapisanych planów z postępem
- `update_plan.py --prefix WARSAW` — podgląd statusu (wykonano X, pozostało Y)
- Aktualizuje tylko przyszłe treningi (od następnego poniedziałku lub `--from-date`)
- Usuwa stare zaplanowania z kalendarza Garmin i stare treningi z biblioteki
- Generuje nowe treningi z nowymi parametrami i wgrywa do Garmin
- Opcja `--from-strava`: automatyczne sugestie ze Stravy przed aktualizacją
- Zachowuje historię (wykonane treningi pozostają niezmienione)
- Stan zapisywany do `~/.triathlon_plans/{PREFIX}.json`

Parametry do aktualizacji: `--ftp`, `--vol-scale`, `--target-time`, `--run-pace`, `--weight`, `--dry-run`

Przykład:
```bash
# Po 2 miesiącach — kalibracja przez Stravę
python3 strava_suggest.py --distance 70.3
python3 update_plan.py --prefix WARSAW --vol-scale 1.1 --ftp 265

# Lub w jednym kroku ze Stravą
python3 update_plan.py --prefix WARSAW --from-strava
```

#### Zapis stanu planu (`~/.triathlon_plans/{PREFIX}.json`)

Wszystkie 4 skrypty planistyczne (`season_plan.py`, `season_plan_en.py`, `generate_plan.py`, `generate_plan_en.py`) zapisują po wgraniu planu plik stanu JSON zawierający:
- konfigurację wyścigu (dystans, data, FTP, waga, vol_scale, tempo biegu)
- listę wgranych treningów z datami i identyfikatorami Garmin (`workout_id`)

Plik stanu jest bazą dla `update_plan.py` i nie jest wymagany do podstawowego użycia.

---

## [1.8.0] — 2026-04-28

### Dodane

#### `strava_suggest.py` — kalibracja planu na podstawie Stravy

Nowy skrypt analizujący ostatnie aktywności Strava i sugerujący parametry planu.

- Czyta tokeny OAuth z `~/.config/strava-mcp/config.json` (auto-refresh przy wygaśnięciu)
- Pobiera aktywności z ostatnich N tygodni (domyślnie 4)
- Liczy tygodniową objętość per sport, średnie tempa, porównuje z bazą dystansu
- Wypisuje gotowe parametry: `--target-time`, `--run-pace`, `--vol-scale`
- Waga i FTP pozostają wpisywane ręcznie (świadoma decyzja użytkownika)

Przykład użycia:
```bash
python3 strava_suggest.py --distance 70.3 --race-date 2026-09-15
python3 strava_suggest.py --distance full --weeks 8
```

#### `--vol-scale` flag w 4 skryptach planistycznych

Mnożnik objętości (default 1.0). Skaluje czasy/dystanse w fazach base/build/taper, zachowując minima dla sesji progowych i tygodnia wyścigu.

- `generate_plan.py` / `generate_plan_en.py`: argparse `--vol-scale`
- `season_plan.py` / `season_plan_en.py`: argparse `--vol-scale` + obsługa `"vol_scale"` w JSON config
- Sugerowane wartości pochodzą z `strava_suggest.py`

### Zmienione

#### README.txt — rozdzielone ścieżki użycia

- Nowy QUICK START z dwoma ścieżkami: PATH A (bez Stravy) i PATH B (ze Stravą, rekomendowana)
- Dodany KROK 4 w sekcji STRAVA MCP — opis `strava_suggest.py` z przykładem wyjścia
- Wszystko w EN+PL

---

## [1.7.0] — 2026-04-06

### Naprawione

#### Logowanie Garmin — OAuth token zamiast 8h cache (wszystkie 4 skrypty)

**Problem:** Wszystkie skrypty logowały się przez SSO przy każdym wygaśnięciu 8h cache, co prowadziło do błędu `429 Rate Limit` (Garmin blokuje IP/konto po zbyt wielu próbach).

**Rozwiązanie:** Podejście z `garth.dumps()` wzorowane na projekcie [export2garmin](https://github.com/RobertWojtowicz/export2garmin):
- Pierwsze logowanie: zapisuje token OAuth do `~/.garmin_token` przez `client.garth.dumps()`
- Kolejne uruchomienia: wczytują token przez `client.login(tokenstore=string)` — bez SSO, bez hasła
- Token ważny tygodnie/miesiące, garth odświeża go automatycznie
- MFA obsługiwane przez `return_on_mfa=True` + `resume_login()`

Dotyczy: `generate_plan.py`, `season_plan.py`, `generate_plan_en.py`, `season_plan_en.py`

#### `generate_plan.py` / `generate_plan_en.py` — brakujący `import os`
- Dodano `import os` (brakowało przy poprzednim refaktoringu SESSION_DIR → TOKEN_FILE)

### Dodane

#### `CLAUDE.md` — reguła logowania OAuth
- Udokumentowany wzorzec `garth.dumps()` / `login(tokenstore=string)`
- Ostrzeżenie: nie używać logowania hasłem przy każdym uruchomieniu

#### `README.txt` — sekcja logowania Garmin (EN + PL)
- Wyjaśnienie mechanizmu tokenu OAuth
- Instrukcja postępowania przy błędzie 429

---

## [1.6.0] — 2026-04-06

### Dodane

#### `mywhoosh_season.py` — Generator plików .zwo dla MyWhoosh / Zwift
- Poprawiony format .zwo: `<Warmup>`, `<Cooldown>`, `<SteadyState>`, `<IntervalsT>` zamiast `<Ramp>`
- Poprawny tag `<name>` (poprzednio błędnie `<n>`)
- Wiadomości tekstowe z wskazówkami treningowymi (`<textevent>`)
- Nowa funkcja `generate_for_distance(prefix, distance, ftp, output_dir)` — generuje plan na podstawie dystansu (sprint/olympic/70.3/full), a nie zakodowanej nazwy wyścigu
- Plany według dystansu: sprint (8 treningów), olympic (10), 70.3 (12), full (16)
- CLI: `--distance` / `--race` / `--list` / `--ftp` / `--output` / `--prefix`

#### Integracja .zwo z głównymi skryptami (wszystkie 4 wersje)
- Po wgraniu planu do Garmin — pytanie: "Wygenerować pliki .zwo dla MyWhoosh/Zwift?"
- Dotyczy: `generate_plan.py`, `season_plan.py`, `generate_plan_en.py`, `season_plan_en.py`
- Pliki generowane do folderu `./mywhoosh_{prefix}/`
- W `season_plan` — generuje osobny folder dla każdego wyścigu w sezonie

---

## [1.5.0] — 2026-04-05

### Dodane

#### Angielskie wersje skryptów
- `generate_plan_en.py` — angielski odpowiednik `generate_plan.py`
- `season_plan_en.py` — angielski odpowiednik `season_plan.py`
- Wersje różnią się wyłącznie napisami wyświetlanymi użytkownikowi (komunikaty, podsumowania splitów)
- Przetłumaczone napisy: `Cel/Pływanie/Rower/Bieg` → `Target/Swim/Bike/Run`, `biegi/pływanie/rower` → `run/swim/bike`
- Logika, strefy, periodyzacja — identyczne w obu wersjach

#### `CLAUDE.md` — reguła dwujęzyczności skryptów
- Każda zmiana logiki lub komunikatów musi być wprowadzona jednocześnie w polskiej i angielskiej wersji skryptu

---

## [1.4.0] — 2026-04-05

### Dodane

#### `README.txt` — Instrukcja Strava MCP dla Claude Code (EN + PL)
- Nowa sekcja: STRAVA MCP — CONNECTING TO CLAUDE CODE / PODŁĄCZENIE DO CLAUDE CODE
- Krok po kroku: tworzenie aplikacji Strava API (strava.com/settings/api, Callback Domain = `localhost`)
- Rejestracja serwera: `claude mcp add --transport stdio strava -- npx @r-huijts/strava-mcp-server`
- Autoryzacja OAuth przez przeglądarkę komendą `"Connect my Strava account"` w Claude Code
- Uwaga o gitignorowanym `.mcp.json` i podejściu z `npx` jako zalecanym

#### `README.txt` — Sekcja planowanego czasu ukończenia (EN + PL)
- Nowa sekcja: TARGET FINISH TIME / PLANOWANY CZAS UKOŃCZENIA
- Wyjaśnia co czas ukończenia wpływa w planie: tempo biegu we wszystkich sesjach biegowych + strefa ZR w Race Sim
- Wyjaśnia co NIE jest pod wpływem: strefy Z1–Z5, objętości, sesje pływackie
- Domyślne wartości ZR per dystans gdy brak czasu docelowego
- Przykład liczbowy: Full Ironman 11:00:00, FTP=234W, waga=75kg

---

## [1.3.0] — 2026-04-05

### Zmienione

#### `generate_plan.py` — Pełna periodyzacja (taka sama jak `season_plan.py`)

Przebudowano `generate_plan()` do tej samej struktury periodyzacji co `generate_race_block()` w `season_plan.py`. Poprzednia wersja generowała **1 sesję/sport/tydzień** (3 treningi/tydzień). Nowa wersja: **2–3 sesje/sport/tydzień**.

**Fazy tygodniowe** (identyczne jak w `season_plan.py`):

| Faza | Sesji/tydzień | Kluczowe sesje |
|---|---|---|
| Baza | 6 (2/sport) | Mon Swim-Tech, Tue Bike-Quality, Wed Run-Tempo, Thu Swim-Endurance + Bike-Z2, Sun Run-Long |
| Budowa | 9 (3/sport) | + Fri Swim-RaceSim + Run-Easy, Sat Bike-Long |
| Tapering | 6 (2/sport) | Skrócone sesje aktywacyjne |
| Tydzień wyścigu | 3 | Pre-race: Bike Check + Run Activation + Swim |

**Dodano** convenience wrappers kroków: `_bwu`, `_bcd`, `_bint`, `_brec`, `_rwu`, `_rcd`, `_rint`, `_swu`, `_scd`, `_sint`, `_wkt` — eliminują powtórzenia kodu.

**Nowe CLI args w `main()`:**
- `--target-time` — docelowy czas ukończenia wyścigu (H:MM:SS)
- `--cda` — współczynnik oporu aerodynamicznego (domyślnie 0.32 m²)

Przy podaniu `--target-time` skrypt oblicza i wyświetla podziały: tempo biegu + moc rowerowa (z modelem fizycznym) + czas pływania.

#### `test_generate_plan.py` — Aktualizacja testów do nowej periodyzacji

- `test_total_sessions_reasonable`: górny próg zmieniony z 6.0 na 10.0 sesji/tydzień (faza budowy: 9/tydzień)
- `test_bike_sessions_on_consistent_days`: górny próg zmieniony z 2 na 4 różne dni tygodnia (baza: D1+D3, budowa: D1+D3+D5, tapering: D1+D4)
- `test_race_week_has_3_sessions` i `test_race_week_sports`: poprawka zero-paddingu tagu (`T{weeks}` → `T{weeks:02d}`) — bez tej poprawki sprint (weeks=8) szukał `TST-T8` zamiast `TST-T08`

---

## [1.2.0] — 2026-04-05

### Dodane

#### `test_generate_plan.py` — Testy jednostkowe generatora planu
- 33 testy pokrywające całą logikę generowania planów (bez logowania do Garmin)
- Uruchamianie: `python -m unittest test_generate_plan -v`
- Klasy testowe:
  - `TestPaceConversion` — przeliczanie MM:SS ↔ m/s, round-trip z tolerancją float
  - `TestWorkoutStructure` — wymagane pola w workout/step, nazwy z prefixem, kolejność stepów
  - `TestGarminTargetRules` — krytyczne reguły API: warmup/cooldown musi mieć `no.target` (id=1, wartości null), interwały rowerowe = `power.zone` (id=2) w watach, interwały biegowe = `pace.zone` (id=6) w m/s, pływanie = `no.target`
  - `TestPowerZones` — wartości Z1/Z2/Z4 zgodne z procentami FTP
  - `TestSessionCounts` — równa liczba sesji per sport, dokładnie 3 sesje w tygodniu wyścigu
  - `TestDatesAndScheduling` — daty w bloku treningowym, format YYYY-MM-DD, spójne dni tygodnia
  - `TestSwimStructure` — `strokeType`/`equipmentType`, `endCondition=distance`, rozsądne dystanse
  - `TestVolumeProgression` — objętość pływania rośnie przez fazę budowy (olympic/70.3/full)
  - `TestFTPSensitivity` — wyższy FTP → wyższe waty; szybsze tempo → wyższe m/s

### Naprawione

#### `generate_plan.py` — Sprint swim floor zbyt wysoki
- Zmieniono `max(400, ...)` na `max(200, ...)` dla dystansu pływackiego tygodnia
- Poprzedni floor 400m blokował progresję wolumenu dla sprintu (wyścig 750m), gdzie szczyt budowy dawał ~450m — objętość nie rosła przez cały blok

---

## [1.1.0] — 2026-04-05

### Zmienione

#### `season_plan.py` — Pełna periodyzacja sesji treningowych

Przebudowano generator bloków treningowych (`generate_race_block`). Poprzednia wersja generowała **1 sesję/sport/tydzień** (3 treningi/tydzień łącznie). Nowa wersja wprowadza periodyzację z **2–3 sesjami/sport/tydzień**.

**Fazy tygodniowe:**

| Faza | Tygodnie (16-tk. plan) | Sesji/tydzień | Opis |
|---|---|---|---|
| Baza | 1–5 | 6 (2/sport) | Mon Swim-Tech, Tue Bike-Quality, Wed Run-Tempo, Thu Swim-Endurance + Bike-Z2, Sun Run-Long |
| Budowa | 6–13 | 9 (3/sport) | + Fri Swim-RaceSim + Run-Easy, Sat Bike-Long |
| Tapering | 14–15 | 6 (2/sport) | Skrócone sesje aktywacyjne |
| Tydzień wyścigu | 16 | 3 | Pre-race: Bike Check + Run Activation + Swim (Piątek) |

**Nowe typy sesji:**
- `Swim Tech` — technika i krótkie interwały (poniedziałek)
- `Swim Endurance` — wytrzymałość pływacka (czwartek)
- `Swim Race-Sim` — symulacja dystansu wyścigowego (piątek, faza budowy)
- `Z2 Endurance` bike — sesja tlenowa (czwartek, obok pływania)
- `Long Ride` bike — długa jazda (sobota, faza budowy)
- `Easy Run` — lekki bieg regeneracyjny (piątek, faza budowy)
- `VO2max 4x5min` bike — zastępuje Z3 Tempo w fazie budowy przy `wk % 3 == 2`
- `Taper Z3` / `Taper Spin` / `Taper Easy` — skrócone sesje w fazie taperu

**Wynik dla Full Ironman (16 tygodni):** 117 sesji (39 bieg / 39 pływanie / 39 rower) vs. 48 w v1.0.0.

**Poprawka drobna:** próg ostrzeżenia o nakładających się datach podniesiony z `> 2` do `> 3` (double-day w czwartek i piątek to zamierzone zachowanie).

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

