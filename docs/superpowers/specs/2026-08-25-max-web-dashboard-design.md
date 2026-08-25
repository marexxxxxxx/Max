# Max — Subprojekt D: Web-Dashboard + Telemetrie (Design-Doc)

- **Datum:** 2026-08-25
- **Status:** Entwurf (Architektur: Ansatz A „Pipeline schreibt, Dashboard liest“)
- **Repo:** `/home/user/max`

## 1. Zweck

Web-Dashboard für Max: Live-Tracking der Anfragen (Tokens, Latenzen pro Pipeline-Stufe), Persistenz in einer SQL-Datenbank und vollständige Agent-Administration (YAML-Profile direkt im Dashboard editieren/erstellen).

## 2. Scope

- **Telemetrie:** pro Anfrage: Timestamp, Sprecher, Text, Agent, remote-Flag, Tokens (Router, Agent, Remote), Latenzen pro Stufe (STT, Router, Agent, TTS, Total).
- **Persistenz:** SQLite (`data/telemetry.db`), eine Zeile pro Anfrage.
- **Live-Tracking:** SSE-Stream neuer Zeilen (selbes Muster wie Display: Poll der DB per Last-seen-Rowid).
- **Agent-Administration:** REST-Endpunkte zum Lesen, Erstellen und Aktualisieren der YAML-Profile in `config/agents/`.
- **Serving:** separates Modul `src/max/dashboard/`, eigener Port (`MAX_DASHBOARD_PORT`, Default 8081), localhost only.

Nicht im Scope: Auth (localhost only), Historical Analytics/Charts, Remote-Server-2-Telemetrie (nur Local-Partial).

## 3. Architektur (Ansatz A: Pipeline schreibt, Dashboard liest)

- **Pipeline** (Prozess `main.py`): misst Stufen-Latenzen und Tokens, schreibt nach jeder Antwort eine Zeile in die SQLite-DB via `TelemetryStore`.
- **Dashboard** (separater Prozess `python -m max.dashboard`): liest dieselbe DB; `http.server`-Pattern wie das Display (localhost, `MAX_DASHBOARD_PORT`).
- Keine IPC, kein In-Memory-Bus — SQLite ist der Single Source of Truth. Pipeline und Dashboard sind unabhängig testbar.

Endpoints des Dashboards:

| Endpoint | Funktion |
|---|---|
| `/` | Static Frontend (`static/index.html`, `static/style.css`) |
| `/api/requests` | Letzte N Zeilen als JSON (Default 50) |
| `/events` | SSE: streamt neue Zeilen (Poll der DB per Last-seen-Rowid, 1 s) |
| `GET /api/agents` | Liste der Agent-Profile (YAML-Dateien) als JSON |
| `POST /api/agents` | Neues Agent-Profil erstellen (YAML-Datei) |
| `PUT /api/agents/<name>` | Agent-Profil aktualisieren (YAML-Datei) |

`main.py` bekommt zusätzlich den Flag `--serve-dashboard` (startet den Dashboard-Server in einem Thread, wie `--serve-display`).

## 4. Datenmodell (SQLite)

```sql
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,                -- ISO-8601-Zeitstempel
  speaker TEXT,
  text TEXT,
  agent TEXT,
  remote_needed INTEGER,   -- 0/1
  tokens_router INTEGER,
  tokens_agent INTEGER,
  tokens_remote INTEGER,
  latency_stt_ms REAL,
  latency_router_ms REAL,
  latency_agent_ms REAL,
  latency_tts_ms REAL,
  latency_total_ms REAL
)
```

- WAL-Modus, `rowid` als Grundlage für den SSE-Poll (Last-seen-Rowid).
- API von `TelemetryStore`: `record(request: dict)`, `recent(limit: int) -> list[dict]`, `since(rowid: int, limit: int) -> list[dict]`.
- Fehlende Werte (z. B. Agent-Latenz bei Remote-Routing) → `NULL`.

## 5. Komponenten

1. **`src/max/telemetry/store.py`** — `TelemetryStore`: Erstellen der Tabelle, `record`, `recent`, `since`. SQLite via stdlib `sqlite3`.
2. **`src/max/telemetry/recorder.py`** — `TelemetryRecorder`: misst Stufen via `start(stage)`/`end(stage)` (Werkzeuguhr), sammelt Token-Zähler (`add_tokens(stage, n)`), erzeugt das Record-Dict.
3. **Pipeline-Integration:**
   - STT-Latenz: im Transcribe-Node des Graphen (Wrapper um `transcriber.transcribe`).
   - Router-Latenz: um den Ollama-Classifier-Call.
   - Agent-Latenz: um den Runner-Call.
   - TTS-Latenz: um `speak()` in `main()`.
   - Total: von Abschluss der Audio-Erfassung bis zum Ende der TTS (Wall-Clock).
   - Tokens: Router-Modelle liefern per API ein `count`/Usage-Wert, wenn vorhanden; sonst Whitespace-Split-Estimate des Antworttextes (explizit: Estimate, kein echter Tokenizer). Remote (Mock) analog.
4. **`src/max/dashboard/server.py`** — `DashboardServer` (http.server, localhost bind), Endpunkte gemäß §3.
5. **`src/max/dashboard/__main__.py`** — Entry-Point `python -m max.dashboard` (Port via `MAX_DASHBOARD_PORT`).
6. **`src/max/dashboard/agents.py`** — YAML-Read/Write der Agent-Profile in `config/agents/` (Wiederverwendung des bestehenden YAML-Parsers aus `src/max/config.py`).
7. **`src/max/dashboard/static/`** — `index.html` + `style.css` (Vanilla JS + SSE).
8. **`src/max/main.py`** — Flag `--serve-dashboard`.

## 6. Agent-Administration

- `GET /api/agents` → JSON-Liste (Name, Beschreibung, Keywords, Capabilities, Pfad).
- `POST /api/agents` → JSON-Body `{name, description, keywords, capabilities}` → schreibt `config/agents/<name>.yaml`.
- `PUT /api/agents/<name>` → aktualisiert bestehende Datei.
- Bei Konflikten (Name existiert bei POST) → `409`, Datei bleibt unverändert.
- Bei invalidem JSON/YAML → `400` mit Fehlermeldung, Datei bleibt unverändert.

## 7. Fehlerbehandlung

| Fehler | Verhalten |
|---|---|
| DB-Fehler bei `record` | Log + Pipeline weiter (Telemetrie crashen nie die Pipeline) |
| Dashboard: DB fehlt/leer | „Keine Daten"-Hinweis im Frontend, kein Crash |
| Invalides Agent-YAML via POST/PUT | `400`, Datei unverändert |
| POST mit existierendem Namen | `409`, Datei unverändert |
| Netzwerk/Timeout | Alles localhost, kein externes Netzwerk |

## 8. Tests

- **Unit:** `TelemetryStore` (record/recent/since, NULL-Handling), `TelemetryRecorder` (Latenzen, Token-Summen), `agents.py` (YAML-Read/Write, Konflikte), `DashboardServer` (Endpoints mit Fake-DB/In-Memory-SQLite), SSE-Events.
- **Integration:** Pipeline (mockte Stufen) → eine Zeile in DB; Dashboard liest die Zeile; SSE streamt sie.
- **E2E:** `python -m max.dashboard` gegen echte DB-Datei (temp), Frontend-Dateien existieren.
- Alle Tests offline, stdlib only (sqlite3, http.server, json, threading).

## 9. Annahmen & offene Punkte

- Port 8081 Default; kein Auth (localhost only, wie Display).
- Token-Zählung: API-Usage wenn vorhanden, sonst Estimate — für Monitoring ausreichend, keine exakte Token-Accounting.
- Agent-Administration mutiert `config/agents/` direkt (keine Backup-Kopie, keine Versionsverwaltung — YAGNI).
- Remote-Server-2-Latenzen werden nur gemessen, wenn MockServer2 im Spiel ist (Subprojekt E erweitert).
