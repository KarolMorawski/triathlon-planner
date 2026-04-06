TRIATHLON SEASON PLANNER
========================
QUICK START:
  1. pip install garminconnect
  2. Edit season_example.json with your races
  3. python3 season_plan.py --config season_example.json --reset

GARMIN LOGIN — FIRST RUN
  On first run you will be asked for email + password (and MFA if enabled).
  After successful login, an OAuth token is saved to: ~/.garmin_token
  All subsequent runs load this token — no password needed, no 429 risk.
  The token is valid for weeks/months and is auto-refreshed by the library.

  If login fails with 429 (rate limit):
    - Wait a few hours (Garmin blocks IPs and accounts after too many attempts)
    - Or reset your Garmin password — this clears the block
    - Do NOT retry login in a loop — each attempt worsens the block

GARMIN LOGOWANIE — PIERWSZE URUCHOMIENIE
  Przy pierwszym uruchomieniu zostaniesz poproszony o email + hasło (i MFA jeśli włączone).
  Po udanym logowaniu token OAuth zostaje zapisany do: ~/.garmin_token
  Kolejne uruchomienia wczytują token — bez hasła, bez ryzyka 429.
  Token jest ważny tygodnie/miesiące i jest automatycznie odświeżany przez bibliotekę.

  Jeśli logowanie kończy się błędem 429 (rate limit):
    - Poczekaj kilka godzin (Garmin blokuje IP i konta po zbyt wielu próbach)
    - Lub zresetuj hasło do Garmin — to zdejmuje blokadę
    - NIE próbuj logować się w pętli — każda próba pogarsza blokadę

COMMANDS:
  python3 season_plan.py --reset                         interactive
  python3 season_plan.py --config season_example.json --reset
  python3 season_plan.py --dry-run                       preview only

DISTANCES: 70.3 / full / olympic / sprint
FULL GUIDE: open INSTRUKCJA.html in Chrome/Firefox

MYWHOOSH / ZWIFT .ZWO FILES
============================
After uploading to Garmin, each script asks:
  "Wygenerować pliki .zwo dla MyWhoosh/Zwift? (tak/nie)"
  (English version: "Generate .zwo files for MyWhoosh/Zwift? (yes/no)")

Answer "tak" / "yes" to generate .zwo workout files automatically.
Files are saved to: ./mywhoosh_{PREFIX}/

You can also run the generator standalone:
  python3 mywhoosh_season.py --ftp 234 --distance 70.3 --prefix WARSAW
  python3 mywhoosh_season.py --list      (show all available plans)

Copy generated files to:
  Mac:     ~/Documents/MyWhoosh/Workouts/
  Windows: Documents\MyWhoosh\Workouts\
  Zwift:   ~/Documents/Zwift/Workouts/<YOUR_ID>/

Workouts per distance:
  sprint   — 8 workouts   olympic — 10 workouts
  70.3     — 12 workouts  full    — 16 workouts

Workout types: Z2 Endurance, Threshold 2x/3x20min, Race Sim,
  Over-Under, VO2max 6x3min, Brick, Taper Spin, Pre-Race Check

---

PLIKI .ZWO DLA MYWHOOSH / ZWIFT
==================================
Po wgraniu planu do Garmin każdy skrypt pyta:
  "Wygenerować pliki .zwo dla MyWhoosh/Zwift? (tak/nie)"

Odpowiedz "tak" aby wygenerować pliki automatycznie.
Pliki zapisywane do: ./mywhoosh_{PREFIX}/

Można też uruchomić generator osobno:
  python3 mywhoosh_season.py --ftp 234 --distance 70.3 --prefix WARSAW
  python3 mywhoosh_season.py --list      (lista dostępnych planów)

Skopiuj pliki do:
  Mac:     ~/Documents/MyWhoosh/Workouts/
  Windows: Documents\MyWhoosh\Workouts\
  Zwift:   ~/Documents/Zwift/Workouts/<TWOJ_ID>/

Liczba treningów per dystans:
  sprint   —  8 treningów  olympic — 10 treningów
  70.3     — 12 treningów  full    — 16 treningów

Typy sesji: Z2 Endurance, Threshold 2x/3x20min, Race Sim,
  Over-Under, VO2max 6x3min, Brick, Taper Spin, Pre-Race Check

USING garmin-venv (recommended)
================================
The repo includes a ready-made virtual environment in garmin-venv/.
Use it to avoid installing garminconnect system-wide.

  macOS / Linux:
    source garmin-venv/bin/activate
    python3 season_plan.py --config season_example.json --reset
    deactivate                          # when done

  Windows (PowerShell):
    garmin-venv\Scripts\Activate.ps1
    python season_plan.py --config season_example.json --reset
    deactivate

  Windows (CMD):
    garmin-venv\Scripts\activate.bat
    python season_plan.py --config season_example.json --reset
    deactivate

While the venv is active your prompt will show (garmin-venv).
To recreate the venv from scratch:
    python3 -m venv garmin-venv
    source garmin-venv/bin/activate
    pip install garminconnect


==========================================================
STRAVA MCP — CONNECTING TO CLAUDE CODE
==========================================================

Strava MCP lets Claude read your Strava activities directly.
You can ask: "How far did I run this month?" or "Analyze my last ride."

REQUIREMENTS
  - Node.js 18+ LTS  (https://nodejs.org)
  - Claude Code CLI  (https://claude.ai/code)

STEP 1 — Create a Strava API application (one-time)
  1. Go to: strava.com/settings/api
  2. Click "Create an App"
  3. Fill in the form:
       Application Name:           anything (e.g. "Claude Assistant")
       Category:                   anything
       Website:                    http://localhost
       Authorization Callback Domain: localhost   ← important!
  4. Copy your Client ID and Client Secret

STEP 2 — Register the MCP server in Claude Code
  Run this command once in any terminal:

    claude mcp add --transport stdio strava -- npx @r-huijts/strava-mcp-server

  Verify it was registered:

    claude mcp list
    # Expected output:
    # strava: npx @r-huijts/strava-mcp-server - ✓ Connected

STEP 3 — Authorize with Strava
  Open Claude Code in any project directory, then type:

    "Connect my Strava account"

  A browser window opens. Enter your Client ID and Client Secret,
  click "Continue to Strava", authorize, and close the browser.
  Credentials are saved at: ~/.config/strava-mcp/config.json

  From now on Strava stays connected across sessions.
  To check: "Am I connected to Strava?"
  To reconnect if needed: "Connect my Strava account"

NOTE: The MCP server is registered globally in Claude Code (not per project).
The .mcp.json file in this repo is gitignored — it may point to a locally
built version of the server and is not required for the npx setup above.

---

STRAVA MCP — PODŁĄCZENIE DO CLAUDE CODE
==========================================================

Strava MCP pozwala Claude czytać Twoje aktywności bezpośrednio ze Stravy.
Możesz pytać: "Ile km przebiegłem w tym miesiącu?" lub "Przeanalizuj ostatni trening."

WYMAGANIA
  - Node.js 18+ LTS  (https://nodejs.org)
  - Claude Code CLI  (https://claude.ai/code)

KROK 1 — Utwórz aplikację Strava API (jednorazowo)
  1. Wejdź na: strava.com/settings/api
  2. Kliknij "Create an App"
  3. Wypełnij formularz:
       Application Name:              cokolwiek (np. "Claude Assistant")
       Category:                      cokolwiek
       Website:                       http://localhost
       Authorization Callback Domain: localhost   ← ważne!
  4. Skopiuj Client ID i Client Secret

KROK 2 — Zarejestruj serwer MCP w Claude Code
  Wykonaj raz w terminalu:

    claude mcp add --transport stdio strava -- npx @r-huijts/strava-mcp-server

  Sprawdź czy działa:

    claude mcp list
    # Oczekiwany wynik:
    # strava: npx @r-huijts/strava-mcp-server - ✓ Connected

KROK 3 — Autoryzacja ze Stravą
  Otwórz Claude Code w dowolnym projekcie i napisz:

    "Connect my Strava account"

  Otworzy się przeglądarka. Wpisz Client ID i Client Secret,
  kliknij "Continue to Strava", autoryzuj i zamknij przeglądarkę.
  Dane logowania są zapisywane w: ~/.config/strava-mcp/config.json

  Od tej pory Strava pozostaje połączona między sesjami.
  Sprawdzenie: "Am I connected to Strava?"
  Ponowne połączenie: "Connect my Strava account"

UWAGA: Serwer MCP jest zarejestrowany globalnie w Claude Code (nie per projekt).
Plik .mcp.json w tym repo jest gitignorowany — może wskazywać na lokalnie
skompilowaną wersję serwera i nie jest wymagany przy podejściu z npx.


==========================================================
TRAINING PLAN ASSUMPTIONS
==========================================================

DISTANCES & BLOCK LENGTH
--------------------------
  sprint   —  8 weeks  | swim  750m | bike  20km | run  5km
  olympic  — 10 weeks  | swim 1500m | bike  40km | run 10km
  70.3     — 12 weeks  | swim 1900m | bike  90km | run 21km
  full     — 16 weeks  | swim 3800m | bike 180km | run 42km

  Block starts are counted back from the race date.
  Example: Full Ironman on 2026-09-12 → block starts 2026-05-23.


PERIODIZATION PHASES
---------------------
  Each block is divided into 4 phases:

  PHASE       WEEKS (16wk example)   SESSIONS/WEEK   VOLUME
  -------     --------------------   -------------   ------
  Base        T01–T05 (first ~1/3)       6           60–77% of peak
  Build       T06–T13 (middle)           9           77–97% of peak
  Taper       T14–T15 (last 2 before     6           50–60% (short)
               race week)
  Race week   T16                        3           pre-race activation only

  Phase boundaries scale proportionally for shorter distances:
    sprint:  base T1-2 | build T3-5  | taper T6-7  | race T8
    olympic: base T1-3 | build T4-7  | taper T8-9  | race T10
    70.3:    base T1-4 | build T5-9  | taper T10-11 | race T12
    full:    base T1-5 | build T6-13 | taper T14-15 | race T16

  Total sessions per distance:
    sprint 54  (18 per sport)  |  olympic 69  (23 per sport)
    70.3   84  (28 per sport)  |  full   117  (39 per sport)


WEEKLY SCHEDULE
----------------
  BASE phase (6 sessions/week):
    Mon  Swim Tech (technique & short intervals)
    Tue  Bike Quality (threshold / race-sim / tempo)
    Wed  Run Tempo (race pace)
    Thu  Swim Endurance + Bike Z2 (double day)
    Sun  Run Long

  BUILD phase (9 sessions/week):
    Mon  Swim Tech
    Tue  Bike Quality (threshold / race-sim / VO2max)
    Wed  Run Tempo
    Thu  Swim Endurance + Bike Z2 (double day)
    Fri  Swim Race-Sim + Run Easy (double day)
    Sat  Bike Long Ride
    Sun  Run Long

  TAPER phase (6 sessions/week, shortened):
    Tue  Bike Taper Z3 (short activation)
    Wed  Run Taper (easy, short)
    Thu  Swim Taper (endurance, reduced)
    Fri  Swim Pre-Race (short) + Bike Spin (double day)
    Sun  Run Taper Easy (very easy)

  RACE week (3 sessions, all on Friday ~3 days before race):
    Fri  Bike Pre-Race Check (20min Z2)
         Run Pre-Race Activation (4km easy)
         Swim Pre-Race (700m easy)


POWER ZONES (cycling) — based on FTP input
--------------------------------------------
  Zone   % FTP     Role
  Z1     40–55%    Warmup, cooldown, recovery intervals
  Z2     60–72%    Aerobic base, long rides, race simulation base
  Z3     76–87%    Tempo — base-phase quality sessions
  Z4     88–97%    Threshold — 3×20min intervals
  Z5    102–112%   VO2max — 4×5min intervals (build phase only)
  ZR    race±3%    Race simulation (see table below)

  Race bike intensity (ZR center):
    sprint   95% FTP
    olympic  88% FTP
    70.3     82% FTP
    full     72% FTP

  Example with FTP=234W:
    Z1  94–129W  |  Z2  140–168W  |  Z3  178–204W
    Z4  206–227W |  Z5  239–262W  |  ZR  (dist-dependent)


BIKE SESSION TYPES
-------------------
  Bike Quality (Tue) rotates every 3 weeks (wk % 3):
    wk%3 == 1  Race Sim     — sustained effort at race pace (ZR)
                               duration: 45–80min (scales with vol)
    wk%3 == 0  Threshold    — 3×20min @ Z4 with 5min Z1 recovery
    wk%3 == 2  Tempo Z3     — base phase, 40–60min @ Z3
               VO2max 4×5min — build phase, 4×5min @ Z5 with 3min recovery

  Bike Z2 Endurance (Thu)  — 45–70min @ Z2, scales with vol
  Bike Long Ride (Sat, build only) — 90–150min @ Z2, scales with vol
  Taper Z3 (Tue)  — 30–45min @ Z3, reduced
  Taper Spin (Fri) — 20–30min @ Z2, very easy


RUN SESSION TYPES
------------------
  Run Tempo (Wed)   — race pace, 6–12km (scales with vol, max 12km)
  Run Long (Sun)    — Z2 pace (93% of race pace), 8–18km
                      max 18km for full/70.3, max 12km for olympic/sprint
  Run Easy (Fri, build only) — easy pace (85% of race pace), 6–9km
  Taper Run (Wed)  — Z2 pace, 5–8km, reduced
  Taper Easy (Sun) — easy pace, 4–6km, very reduced
  Pre-Race (Fri)   — 4km easy (500m warmup + 3km + 500m cooldown)

  Run pace zones derived from input race pace:
    Easy   = race pace × 0.85  (slower)
    Z2     = race pace × 0.93
    Race   = input pace (MM:SS/km)

  Example with race pace 5:10/km:
    Easy   ~6:04/km  |  Z2  ~5:33/km  |  Race  5:10/km


SWIM SESSION TYPES
-------------------
  All swim sessions: warmup + main set + 100m cooldown.
  No pace target — distance-based only (Garmin swim format).

  Swim Tech (Mon)
    — 55% of weekly swim volume
    — min 600m
    — purpose: technique drills and short intervals

  Swim Endurance (Thu)
    — 75% of weekly swim volume
    — min 800m
    — purpose: sustained aerobic distance

  Swim Race-Sim (Fri, build only)
    — scales to ~85% of race swim distance × vol factor
    — 67–84% of race distance (grows through build phase)
    — purpose: race-pace effort, approaching race distance
    Examples at peak build:
      sprint  ~600m  (race 750m)   | olympic ~1200m (race 1500m)
      70.3  ~1600m  (race 1900m)  | full    ~3100m (race 3800m)

  Weekly swim volume base = race_swim_distance × 60% × vol_factor
  where vol_factor rises from 0.63 (week 1) to ~1.0 (peak build week).

  Taper Swim (Thu)   — 40% of race distance × vol, min 800m
  Taper Pre-Race (Fri) — 25% of race distance × vol, min 400m
  Pre-Race Swim (race week Fri) — fixed 700m easy


VOLUME PROGRESSION
-------------------
  Volume factor (vol) controls all distances and durations:

    Base phase:   vol = 0.63 → 0.77  (linear ramp to taper start)
    Build phase:  vol = 0.77 → 0.97  (continues same ramp)
    Taper:        vol = 0.60 → 0.50  (steps down with remaining weeks)
    Race week:    vol = 0.30          (minimal)

  The ramp formula: vol = min(1.0, 0.6 + wk / taper_start_week × 0.4)
  Peak vol reaches ~1.0 only in the last build week before taper.


TARGET FINISH TIME (optional)
------------------------------
  Both scripts ask for a target finish time during interactive setup.
  It is optional — you can also provide run pace directly instead.

  When target time is provided, the script back-calculates:
    - Run pace (MM:SS/km) — derived from run split
    - Bike race zone ZR   — derived from required bike power (physics model)
    - Also shown: swim split, T1+T2 estimate, bike speed

  What target time AFFECTS in the plan:
    Run pace in ALL run sessions (Tempo, Long Run, Easy Run, Pre-Race).
      Faster target → higher m/s in every run step.
    ZR bike zone used in Race Sim sessions (Tue quality rotation).
      Faster target → higher % FTP for Race Sim intervals.

  What target time does NOT affect:
    Zones Z1–Z5 — these depend only on FTP input, not finish time.
    Session volumes, distances, durations — controlled by periodization.
    Swim sessions — no pace target in Garmin swim format.

  If no target time is given, ZR defaults to the profile value:
    sprint 95% FTP | olympic 88% FTP | 70.3 82% FTP | full 72% FTP

  Example: Full Ironman target 11:00:00, FTP=234W, weight=75kg
    → Swim: ~1:20  T1+T2: ~0:10  Bike: ~5:45 @ ~171W (73% FTP)
    → Run:  ~3:45  @ 5:20/km
    Bike sessions Race Sim use ZR = 70–76% FTP instead of 69–75%.


==========================================================
ZAŁOŻENIA PLANU TRENINGOWEGO
==========================================================

DYSTANSE I DŁUGOŚĆ BLOKU
--------------------------
  sprint   —  8 tygodni  | pływanie  750m | rower  20km | bieg  5km
  olympic  — 10 tygodni  | pływanie 1500m | rower  40km | bieg 10km
  70.3     — 12 tygodni  | pływanie 1900m | rower  90km | bieg 21km
  full     — 16 tygodni  | pływanie 3800m | rower 180km | bieg 42km

  Blok liczony wstecz od daty wyścigu.
  Przykład: Full Ironman 2026-09-12 → blok startuje 2026-05-23.


FAZY PERIODYZACJI
------------------
  Każdy blok podzielony jest na 4 fazy:

  FAZA          TYGODNIE (plan 16-tk.)   SESJI/TYG.   OBJĘTOŚĆ
  -------       ----------------------   ----------   --------
  Baza          T01–T05 (pierwsze ~1/3)      6        60–77% szczytu
  Budowa        T06–T13 (środek)             9        77–97% szczytu
  Tapering      T14–T15 (ostatnie 2 przed    6        50–60% (skrócone)
                 tygodniem wyścigu)
  Tydzień wyśc. T16                          3        tylko aktywacja

  Granice faz skalują się proporcjonalnie dla krótszych dystansów:
    sprint:  baza T1-2 | budowa T3-5  | taper T6-7  | wyścig T8
    olympic: baza T1-3 | budowa T4-7  | taper T8-9  | wyścig T10
    70.3:    baza T1-4 | budowa T5-9  | taper T10-11 | wyścig T12
    full:    baza T1-5 | budowa T6-13 | taper T14-15 | wyścig T16

  Łączna liczba sesji per dystans:
    sprint 54  (18 per sport)  |  olympic 69  (23 per sport)
    70.3   84  (28 per sport)  |  full   117  (39 per sport)


TYGODNIOWY ROZKŁAD TRENINGÓW
------------------------------
  Faza BAZA (6 sesji/tydzień):
    Pon  Pływanie Tech (technika i krótkie interwały)
    Wt   Rower Jakościowy (threshold / race-sim / tempo)
    Śr   Bieg Tempo (tempo wyścigowe)
    Czw  Pływanie Wytrzymałościowe + Rower Z2 (dwa treningi)
    Nd   Bieg Długi

  Faza BUDOWA (9 sesji/tydzień):
    Pon  Pływanie Tech
    Wt   Rower Jakościowy (threshold / race-sim / VO2max)
    Śr   Bieg Tempo
    Czw  Pływanie Wytrzymałościowe + Rower Z2 (dwa treningi)
    Pt   Pływanie Race-Sim + Bieg Łatwy (dwa treningi)
    Sob  Rower Długi
    Nd   Bieg Długi

  Faza TAPERING (6 sesji/tydzień, skrócone):
    Wt   Rower Taper Z3 (krótka aktywacja)
    Śr   Bieg Taper (łatwy, krótki)
    Czw  Pływanie Taper (wytrzymałościowe, skrócone)
    Pt   Pływanie Pre-Race (krótkie) + Rower Spin (dwa treningi)
    Nd   Bieg Taper Łatwy (bardzo spokojny)

  Tydzień WYŚCIGU (3 sesje, wszystkie w piątek ~3 dni przed startem):
    Pt   Rower Pre-Race Check (20min Z2)
         Bieg Aktywacja (4km łatwo)
         Pływanie Pre-Race (700m łatwo)


STREFY MOCY (rower) — na podstawie FTP
----------------------------------------
  Strefa  % FTP     Zastosowanie
  Z1      40–55%    Rozgrzewka, schłodzenie, przerwy w interwałach
  Z2      60–72%    Baza tlenowa, długie jazdy, podstawa race-sim
  Z3      76–87%    Tempo — sesje jakościowe w fazie bazy
  Z4      88–97%    Threshold — interwały 3×20min
  Z5     102–112%   VO2max — interwały 4×5min (tylko faza budowy)
  ZR     wyścig±3%  Symulacja wyścigu (patrz tabela poniżej)

  Intensywność jazdy wyścigowej (środek ZR):
    sprint   95% FTP
    olympic  88% FTP
    70.3     82% FTP
    full     72% FTP

  Przykład dla FTP=234W:
    Z1  94–129W  |  Z2  140–168W  |  Z3  178–204W
    Z4  206–227W |  Z5  239–262W  |  ZR  (zależne od dystansu)


TYPY SESJI ROWEROWYCH
----------------------
  Rower Jakościowy (Wt) rotuje co 3 tygodnie (numer_tygodnia % 3):
    t%3 == 1  Race Sim      — ciągły wysiłek w tempie wyścigu (ZR)
                               czas: 45–80min (skaluje się z vol)
    t%3 == 0  Threshold     — 3×20min @ Z4 z 5min przerwy @ Z1
    t%3 == 2  Tempo Z3      — faza bazy, 40–60min @ Z3
               VO2max 4×5min — faza budowy, 4×5min @ Z5 z 3min przerwy

  Rower Z2 Wytrzymałość (Czw) — 45–70min @ Z2, skaluje się z vol
  Rower Długi (Sob, tylko budowa) — 90–150min @ Z2, skaluje się z vol
  Taper Z3 (Wt)  — 30–45min @ Z3, skrócony
  Taper Spin (Pt) — 20–30min @ Z2, bardzo spokojny


TYPY SESJI BIEGOWYCH
---------------------
  Bieg Tempo (Śr)    — tempo wyścigowe, 6–12km (skaluje z vol, max 12km)
  Bieg Długi (Nd)    — tempo Z2 (93% tempa wyścigowego), 8–18km
                       max 18km dla full/70.3, max 12km dla olympic/sprint
  Bieg Łatwy (Pt, tylko budowa) — łatwe tempo (85% wyścigowego), 6–9km
  Bieg Taper (Śr)   — tempo Z2, 5–8km, skrócony
  Bieg Taper Łatwy (Nd) — łatwe tempo, 4–6km, mocno skrócony
  Pre-Race (Pt)      — 4km łatwo (500m rozgrzewka + 3km + 500m schłodzenie)

  Strefy tempa biegu na podstawie podanego tempa wyścigowego:
    Łatwe  = tempo wyścigowe × 0.85  (wolniej)
    Z2     = tempo wyścigowe × 0.93
    Wyścig = podane tempo (MM:SS/km)

  Przykład dla tempa 5:10/km:
    Łatwe  ~6:04/km  |  Z2  ~5:33/km  |  Wyścig  5:10/km


TYPY SESJI PŁYWACKICH
----------------------
  Wszystkie sesje: rozgrzewka + główny zestaw + 100m schłodzenie.
  Brak celu tempa — tylko dystans (format pływania Garmin).

  Pływanie Tech (Pon)
    — 55% tygodniowej objętości pływania
    — min 600m
    — cel: technika i krótkie interwały

  Pływanie Wytrzymałościowe (Czw)
    — 75% tygodniowej objętości pływania
    — min 800m
    — cel: ciągły dystans tlenowy

  Pływanie Race-Sim (Pt, tylko budowa)
    — skaluje do ~85% dystansu pływackiego wyścigu × współczynnik vol
    — 67–84% dystansu wyścigu (rośnie przez fazę budowy)
    — cel: wysiłek w tempie wyścigowym, zbliżanie się do dystansu
    Przykłady przy szczycie budowy:
      sprint  ~600m  (wyścig 750m)   | olympic ~1200m (wyścig 1500m)
      70.3  ~1600m  (wyścig 1900m)  | full    ~3100m (wyścig 3800m)

  Tygodniowa objętość bazy = dystans_pływacki × 60% × współczynnik_vol
  Współczynnik vol rośnie od 0.63 (tydzień 1) do ~1.0 (szczyt budowy).

  Pływanie Taper (Czw)    — 40% dystansu wyścigu × vol, min 800m
  Pływanie Pre-Race (Pt)  — 25% dystansu wyścigu × vol, min 400m
  Pre-Race Swim (piątek tygodnia wyścigowego) — stałe 700m łatwo


PROGRESJA OBJĘTOŚCI
--------------------
  Współczynnik vol kontroluje wszystkie dystanse i czasy trwania:

    Faza bazy:    vol = 0.63 → 0.77  (liniowy wzrost do startu taperu)
    Faza budowy:  vol = 0.77 → 0.97  (kontynuacja tego samego wzrostu)
    Tapering:     vol = 0.60 → 0.50  (spada wraz z pozostałymi tygodniami)
    Tydzień wyśc: vol = 0.30          (minimalny)

  Wzór: vol = min(1.0, 0.6 + numer_tygodnia / tydzień_startu_taperu × 0.4)
  Szczyt vol ~1.0 osiągany tylko w ostatnim tygodniu budowy przed taperem.


PLANOWANY CZAS UKOŃCZENIA (opcjonalny)
----------------------------------------
  Oba skrypty pytają o planowany czas ukończenia wyścigu podczas konfiguracji.
  Jest opcjonalny — zamiast niego można podać bezpośrednio tempo biegu.

  Gdy podany jest czas ukończenia, skrypt wylicza wstecz:
    - Tempo biegu (MM:SS/km) — z podziału czasu na bieg
    - Strefę rowerową ZR     — z wymaganej mocy (model fizyczny)
    - Wyświetla też: czas pływania, szacunek T1+T2, prędkość rowerową

  Na co czas ukończenia MA wpływ w planie:
    Tempo biegu we WSZYSTKICH sesjach biegowych (Tempo, Długi, Łatwy, Pre-Race).
      Szybszy cel → wyższe m/s w każdym stepie biegowym.
    Strefa ZR w sesjach Race Sim (rotacja jakościowa Wt).
      Szybszy cel → wyższy % FTP w interwałach Race Sim.

  Na co czas ukończenia NIE MA wpływu:
    Strefy Z1–Z5 — zależą wyłącznie od FTP, nie od czasu docelowego.
    Objętości sesji, dystanse, czasy trwania — kontrolowane przez periodyzację.
    Sesje pływackie — format pływania Garmin nie obsługuje celu tempa.

  Jeśli nie podano czasu, ZR przyjmuje domyślne wartości profilowe:
    sprint 95% FTP | olympic 88% FTP | 70.3 82% FTP | full 72% FTP

  Przykład: Full Ironman cel 11:00:00, FTP=234W, waga=75kg
    → Pływanie: ~1:20  T1+T2: ~0:10  Rower: ~5:45 @ ~171W (73% FTP)
    → Bieg:     ~3:45  @ 5:20/km
    Sesje Race Sim używają ZR = 70–76% FTP zamiast domyślnych 69–75%.
