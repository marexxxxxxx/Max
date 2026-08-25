# Max — Smart Mirror / Display (Design-Doc, Subprojekt C)

- **Datum:** 2026-08-25
- **Status:** Design vom Nutzer bestätigt
- **Repo:** `/home/user/max`
- **Vorausgesetzt:** Subprojekt A (Walking Skeleton) und B (Agenten-Plattform) sind umgesetzt

## 1. Zweck

Ein **Smart Mirror** für den Haushalt: eine lokal servierte Web-Seite, auf der Routine-Infos (Uhrzeit, Wetter, Kalender) und **Agent-Cards** angezeigt werden. Jeder Fach-Agent der Plattform kann domänenspezifische Inhalte auf dem Display anzeigen, indem er eine **Card-JSON-Datei** schreibt — ohne dass der Agent Bash oder ein HTTP-Client braucht.

## 2. Kernentscheidungen (vom Nutzer bestätigt)

| Thema | Entscheidung |
|---|---|
| Realisierung | Beliebiges Monitor/TV am PC: Max serviert eine lokale Web-Seite (Option B) |
| Inhalte | Standard-Cards (Ernährungsplan, Uhrzeit+Wetter, Kalender) **und** jeder Agent kann eigene domänenspezifische Cards anzeigen |
| Aktualisierung | Mischform: Routine-Daten per Polling, Agent-Pushes live per SSE (Server-Sent Events) |
| Anzeige | **Nur Cards** — kein Transkript/gesprochene Antworten von Max auf dem Display |
| Agent-Push | Datei-basiert: Agent schreibt `data/display/cards/<agent>.json`; Display-Server pollt das Verzeichnis und streamt Änderungen per SSE |
| Wetter | Freier HTTP-Service (open-meteo, ohne API-Key), best-effort; offline → Card ausgeblendet |
| Kalender | Lokale JSON-Datei (`config/calendar.json`), einfache Events-Liste; später ersetzbar (z. B. CalDAV) |
| Reserven (nicht jetzt) | MCP-Server für ein „extra Fenster" — als Ausbaustep dokumentiert, **nicht** in C implementiert |
| Dependencies | Keine neuen Python-Dependencies (stdlib `http.server`, `urllib`); offline Tests |
| Sprache/UI | Deutsche Beschriftungen |

## 3. Architektur

```
Display-Server (lokal, stdlib http.server)
  ├── GET /            → index.html (Cards-Grid, vanilla JS)
  ├── GET /api/cards   → JSON: alle Cards (Routine + Agent-Cards)
  └── GET /events      → SSE-Stream: push bei Agent-Card-Änderung

Cards-Quellen:
  - Routine (vom Server erzeugt): clock (live), weather (open-meteo, geocacht), calendar (config/calendar.json)
  - Agent-Cards: data/display/cards/<agent>.json (geschrieben von opencode-Agenten)
```

- Der Display-Server läuft lokal (default `127.0.0.1:8080`, Port via `MAX_DISPLAY_PORT`).
- Der Server startet unabhängig von der Voice-Pipeline: `python -m max.display` (eigener Entry-Point), optional auch als Thread aus `main.py` (Option `--serve-display`).
- Verzeichnis `data/display/cards/` wird alle ~2–3 s gecheckt; bei geänderter `updated_at` wird die neue Card per SSE an alle Clients gesendet.

### 3.1 Card-JSON-Schema

```json
{
  "agent": "ernaehrungsplaner",
  "title": "Heute: Ernährung",
  "type": "meal",
  "data": {
    "breakfast": "Haferbrei mit Banane",
    "lunch": "Hähnchen mit Reis",
    "dinner": "Lachs mit Kartoffeln"
  },
  "updated_at": "2026-08-25T12:30:00+00:00"
}
```

- `type` bestimmt das Template: `meal`, `weather`, `calendar`, `clock`, `generic`.
- Ungültige/inkonsistente Cards werden ignoriert (Display bleibt stabil), Fehler in die Server-Logs.
- `generic`: Freie Card mit `data` als flachem Key/Value-Objekt — erlaubt jedem Agent domänenspezifische Inhalte ohne neue Templates.

### 3.2 Standard-Cards (Server-erzeugt)

- **clock:** Uhrzeit (ISO `HH:MM`), wird clientseitig fortlaufend aktualisiert (keine Polling-Last).
- **weather:** open-meteo (free, no key), einmaliger Fetch pro Stunde (Cache), Standort über Env (`MAX_WEATHER_LAT`, `MAX_WEATHER_LON`, Default 51.0/13.75). Offline/HTTP-Fehler → Card wird nicht im JSON (Display blendet aus).
- **calendar:** `config/calendar.json`:
  ```json
  {"events": [{"date": "2026-08-25", "title": "Dentist"}]}
  ```
  Heute + morgige Events werden in der Card zusammengefasst.

### 3.3 Agent-Integration

- opencode-Agenten dürfen `edit` + `external_directory` → sie schreiben ihre Card in `data/display/cards/<agent>.json`.
- Der Ernährungsplaner-Prompt (`config/opencode/ernaehrungsplaner.prompt.md`) wird erweitert: „Nach dem Planen schreibe deine Card in `<card_pfad>` (Schema im Prompt). Der Card-Pfad wird der Task-Nachricht mitgegeben (aus `data/display/cards/` abgeleitet)."
- Generische Regelung für spätere Agenten: der Task-Prompt enthält immer den Card-Pfad und das Schema; jeder Agent kann ohne Code-Änderungen eine eigene Card pushen.

## 4. Frontend

- `src/max/display/static/index.html` + `style.css` — vanilla HTML/CSS/JS, kein Framework, kein Build-Step.
- `fetch('/api/cards')` beim Start + Polling alle ~5 s für Routine-Änderungen.
- `EventSource('/events')` für Agent-Card-Updates (SSE); auf `message` → Card-Neuzeichnung ohne Reload.
- Cards-Grid: pro Card eine Box mit Titel + typspezifischem Layout (meal: 3 Zeilen; weather: Temperatur+Icon-Text; calendar: Liste; generic: Key/Value).
- Keine Anzeige von gesprochenen Antworten (explizit nicht gewünscht).

## 5. Module & Files

- `src/max/display/__init__.py`
- `src/max/display/cards.py` — Card-Modell, Validierung, Verzeichnis-Reading/Watching (Polling)
- `src/max/display/providers.py` — Routine-Cards: clock, weather (open-meteo via `urllib`), calendar
- `src/max/display/server.py` — HTTP-Server (`http.server`), Endpunkte `/`, `/api/cards`, `/events` (SSE)
- `src/max/display/__main__.py` — Entry-Point: `python -m max.display`
- `src/max/display/static/index.html`, `style.css`
- `config/calendar.json` — lokale Kalenderdaten
- `tests/test_display_cards.py`, `tests/test_display_providers.py`, `tests/test_display_server.py`
- `config/opencode/ernaehrungsplaner.prompt.md` — Erweiterung um Card-Write-Anweisung
- `src/max/main.py` — optional: `--serve-display` startet den Display-Server als Thread

## 6. Constraints

- Keine neuen Python-Dependencies (stdlib only: `http.server`, `urllib`, `json`, `threading`).
- Tests laufen offline: open-meteo wird gemockt (injected fetcher), Display-Server-Tests mit `urllib` gegen ein ephemeres Port oder direkte Funktionstests.
- Deutsches UI und deutsche Strings in Cards/Protokoll.
- Fehler-Toleranz: Wetter-Offline, fehlende/defekte Cards, fehlende `calendar.json` → Display zeigt nur das, was funktioniert (kein Absturz).
- Security: nur localhost-Bind (keine Remote-Anbindung in C).

## 7. Non-Goals (nicht in C)

- MCP-Server für „extra Fenster"/weitere Display-Kanäle (reserviert für später)
- Touchscreen/Hardware-Anbindung, Spiegel-Optik
- Remote-Zugriff (Firewall/HTTPS), Benutzerverwaltung
- CalDAV/Google-Kalender-Anbindung (später ersetzbar)

## 8. Teststrategie (offline)

| Test | Inhalt |
|---|---|
| `test_display_cards.py` | Card-Validierung (Schema, `type`, `updated_at`), Verzeichnis-Loading, defekte Cards ignoriert |
| `test_display_providers.py` | weather mit mocked fetcher (online/offline-Fall), calendar aus JSON, clock deterministisch |
| `test_display_server.py` | Endpunkte `/`, `/api/cards`, `/events` gegen ephemeres Port (`urllib`); SSE-Meldung bei simulierter Card-Änderung |
| `test_display_e2e.py` | Fixtures: Agent-Card-Datei geschrieben → erscheint in `/api/cards`; SSE-Ereignis gesendet |

## 9. Abhängigkeiten & Reihenfolge

- C setzt B voraus (Agent-Plattform existiert) und A (Repository-Grundgerüst).
- `data/display/cards/` wird in `.gitignore` aufgenommen (`.gitignore` bereits ignoriert `data/`).

## 10. offene Punkte (bewusst offen)

- Wetter-Standort: via Env, Default Berlin — Nutzer kann ändern.
- Kalender-Quelle: lokal JSON in C; CalDAV/G später.
- MCP-Server: Architektur-Hook (Card-Writer-Interface) wird so designed, dass ein späterer MCP-Server denselben Card-Verzeichnis-Vertrag nutzen kann.
