# CLAUDE.md — Triathlon Training Planner

## Projekt
Generator planów treningowych dla triathlonistów.
Wgrywa treningi do Garmin Connect przez oficjalne API.
Obsługiwane dystanse: 70.3, full, olympic, sprint.

## Stack
- Python 3.10+
- garminconnect 0.3.x (pip)
- venv w folderze: garmin-venv/
- Aktywacja: source garmin-venv/bin/activate (Mac/Linux)
- Aktywacja: garmin-venv\Scripts\activate (Windows)

## Pliki kluczowe
- season_plan.py      — główny: plan sezonu, wiele zawodów
- season_plan_en.py   — angielska wersja season_plan.py
- generate_plan.py    — plan jednych zawodów (interaktywny lub CLI)
- generate_plan_en.py — angielska wersja generate_plan.py
- mywhoosh_season.py  — generator plików .zwo dla MyWhoosh / Zwift
- season_example.json — szablon konfiguracji sezonu
- CHANGELOG.md        — historia zmian (aktualizuj przy każdej zmianie)
- INSTRUKCJA.html     — instrukcja dla użytkowników końcowych

## Format .zwo (MyWhoosh / Zwift) — potwierdzone empirycznie
```
POPRAWNIE:
  <Warmup>      dla rozgrzewki (PowerLow → PowerHigh)
  <Cooldown>    dla schłodzenia (PowerLow → PowerHigh)
  <SteadyState> dla bloków stałej mocy (Power jako % FTP, np. 0.82)
  <IntervalsT>  dla interwałów (OnPower/OffPower jako % FTP)
  <name>        tag nazwy treningu

BŁĘDY których unikamy:
  <Ramp>   — nie obsługiwany poprawnie przez MyWhoosh
  <n>      — błędny tag nazwy (powinno być <name>)
```

## Garmin API — potwierdzone empirycznie przez analizę sieciową

### Power target (rower) — KRYTYCZNE
```
POPRAWNIE (interval/recovery):
  workoutTargetTypeId  = 2
  workoutTargetTypeKey = "power.zone"
  targetValueOne/Two   = absolutne waty (np. 158.0, 184.0)

POPRAWNIE (warmup/cooldown):
  workoutTargetTypeId  = 1
  workoutTargetTypeKey = "no.target"
  targetValueOne/Two   = null

BŁĄD który naprawiono:
  targetTypeId=5 na jakimkolwiek kroku → Garmin wyświetla jako kph
  power target na warmup/cooldown → Garmin wyświetla jako kph
  Mechanizm błędu: wartość_w_watach × 3.6 = wyświetlane_kph
```

### Pace target (bieg)
```
workoutTargetTypeId  = 6
workoutTargetTypeKey = "pace.zone"
targetValueOne/Two   = m/s (przeliczenie: 1000 / (minuty*60 + sekundy))
Przykład: 5:20/km → 1000/320 = 3.125 m/s
```

### No target
```
workoutTargetTypeId  = 1
workoutTargetTypeKey = "no.target"
targetValueOne/Two   = null
```

### Sport IDs
```
running  = 1
cycling  = 2
swimming = 4
```

### garminconnect 0.3.x
```python
# 0.3.3+: http client dostępny przez client.client (nie client.garth)
http = client.client

# DELETE zaplanowania z kalendarza
http.request("DELETE", "connectapi", f"/workout-service/schedule/{sid}", api=True)

# DELETE treningu z biblioteki
http.request("DELETE", "connectapi", f"/workout-service/workout/{wid}", api=True)

# Pobierz kalendarz (miesiąc 0-indexed!)
client.connectapi(f"/calendar-service/year/{year}/month/{0_indexed_month}")
```

### Logowanie — OAuth token (client.dumps)
```python
TOKEN_FILE = os.path.expanduser("~/.garmin_token")

# Pierwsze logowanie — zapisz token
client = Garmin(email, password, return_on_mfa=True)
result, state = client.login()
if result == "needs_mfa":
    client.resume_login(state, mfa_code)
open(TOKEN_FILE, "w").write(client.client.dumps())

# Kolejne uruchomienia — wczytaj token (bez SSO, bez ryzyka 429)
client = Garmin()
client.login(tokenstore=open(TOKEN_FILE).read())
```
- Token ważny tygodnie/miesiące, biblioteka odświeża go automatycznie
- NIE używać starego podejścia (login hasłem przy każdym uruchomieniu) — powoduje 429
- Token współdzielony przez wszystkie 4 skrypty (`~/.garmin_token`)

### schedule vs workout
- workoutId = ID treningu w bibliotece Garmin
- scheduleId = ID zaplanowania w kalendarzu (oddzielne od workoutId)
- Bug v1.0.0: stary scheduleId wskazywał na stary workoutId po re-upload

## Konwencje kodu

### Prefixy wyścigów
- Każdy wyścig ma unikalny PREFIX (np. WARSAW, BERLIN, POZNAN)
- --reset usuwa tylko treningi z danym prefixem
- Nazwy treningów: PREFIX-T01 Z2 Endurance 60min @153-184W

### Strefy mocy (FTP=255W jako przykład)
- Z1: 40-55% FTP (102-140W) — warmup, cooldown, recovery
- Z2: 60-72% FTP (153-184W) — baza aerobowa, główna strefa triathlonu
- Z3: 76-87% FTP (194-222W) — tempo
- Z4: 88-97% FTP (224-247W) — threshold, interwały
- Z5: 102-112% FTP (260-286W) — VO2max
- Race 70.3: 79-85% FTP (~82% środek) — tempo wyścigu 90km

### README.txt — konwencja językowa
- Po każdej sekcji angielskiej dodawaj jej polskie tłumaczenie
- Zawsze obie wersje: najpierw angielska, bezpośrednio pod nią polska

### Wersje językowe skryptów
- Każdy skrypt istnieje w dwóch wersjach: polska (`season_plan.py`, `generate_plan.py`) i angielska (`season_plan_en.py`, `generate_plan_en.py`)
- Każda zmiana logiki lub komunikatów musi być wprowadzona w obu wersjach jednocześnie
- Wersja angielska różni się tylko napisami wyświetlanymi użytkownikowi — logika identyczna

### Pliki testowe
- Po napisaniu testów i potwierdzeniu, że wszystkie przechodzą — usuń plik testowy
- Testy służą do weryfikacji logiki podczas developmentu, nie są częścią produktu końcowego
- Wyjątek: nie usuwaj jeśli użytkownik wyraźnie prosi o zachowanie testów

### Format commitów git
- feat: nowa funkcja
- fix: naprawa błędu
- docs: dokumentacja, changelog
- refactor: refaktoring bez zmiany funkcjonalności
- test: testy

## Backlog (planowane funkcje)
- [ ] Zapis tokenu sesji Garmin (brak potrzeby logowania przy każdym uruchomieniu)
- [ ] Repeat groups (interwały z powtórzeniami w natywnym formacie Garmin)
- [ ] Generator .zwo zintegrowany z pakietem (teraz: oddzielny mywhoosh_season.py)
- [ ] Eksport planu do CSV / PDF
- [ ] Automatyczne FTP z API Garmin lub Strava
- [ ] SKILL.md dla claude.ai po pierwszym sezonie produkcyjnym
