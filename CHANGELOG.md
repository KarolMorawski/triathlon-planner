# Changelog — Triathlon Training Planner

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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

