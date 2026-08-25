# Subprojekt D — Web-Dashboard + Telemetrie: Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Separate Web-Dashboard (port 8081) mit Live-Tracking der Anfragen, SQLite-Telemetrie (Latenzen, Tokens) und Agent-Administration (YAML-Edit via REST).

**Architecture:** Approach A — Pipeline schreibt (`src/max/telemetry/`), Dashboard liest (`src/max/dashboard/`). SQLite als einzige Quelle der Wahrheit.

**Tech Stack:** Python 3.12, stdlib (`sqlite3`, `http.server`, `json`, `threading`, `urllib.request`, `socket`), `yaml` (existing dep). Keine neuen Abhängigkeiten.

**Global Constraints:**
- Alle Tests offline (keine Ollama, kein Netzwerk, kein Microphone).
- Telemetrie darf die Pipeline nie crashen (try/except, log, weiter).
- Dashboard bindet auf localhost, kein Auth.
- Deutsche Strings und Comments.
- `data/telemetry.db` wird gitignored (data/ ist bereits ignored).

## Task 1: TelemetryStore

**Files:**
- Create: `src/max/telemetry/__init__.py`
- Create: `src/max/telemetry/store.py`
- Create: `tests/test_telemetry_store.py`

**TDD Steps:**
1. Write failing tests in `tests/test_telemetry_store.py`:
   - `test_record_and_recent` — record 2 dicts → `recent(10)` returns 2 rows, newest first, values match.
   - `test_recent_limit` — record 3, `recent(2)` → 2 rows, newest first.
   - `test_since` — record 3, `since(first_id)` → the 2 newer rows, ascending.
   - `test_missing_values_are_null` — record without latencies/tokens → row has `None` for those fields.
   - `test_max_rowid` — empty store → 0; after 2 records → 2.
2. Run: `cd /home/user/max && uv run pytest tests/test_telemetry_store.py` → FAIL (module missing).
3. Implement `src/max/telemetry/store.py`:

```python
"""Telemetrie-Store: persistiert Anfragen in SQLite (data/telemetry.db).

Eine Zeile pro Anfrage. Fehlende Werte bleiben NULL.
"""
import datetime
import os
import sqlite3

COLUMNS = (
    "ts", "speaker", "text", "agent", "remote_needed",
    "tokens_router", "tokens_agent", "tokens_remote",
    "latency_stt_ms", "latency_router_ms",
    "latency_agent_ms", "latency_tts_ms", "latency_total_ms",
)


class TelemetryStore:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS requests ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "ts TEXT, speaker TEXT, text TEXT, agent TEXT,"
            "remote_needed INTEGER,"
            "tokens_router INTEGER, tokens_agent INTEGER, tokens_remote INTEGER,"
            "latency_stt_ms REAL, latency_router_ms REAL,"
            "latency_agent_ms REAL, latency_tts_ms REAL, latency_total_ms REAL)"
        )
        self._conn.commit()

    def record(self, req: dict) -> int:
        """Schreibt eine Zeile. Fehlende Keys werden NULL gespeichert. Liefert die id."""
        values = tuple(req.get(col) for col in COLUMNS)
        cur = self._conn.execute(
            "INSERT INTO requests (ts, speaker, text, agent, remote_needed,"
            "tokens_router, tokens_agent, tokens_remote,"
            "latency_stt_ms, latency_router_ms, latency_agent_ms,"
            "latency_tts_ms, latency_total_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )
        self._conn.commit()
        return cur.lastrowid

    def _rows(self, sql: str, args) -> list[dict]:
        cur = self._conn.execute(sql, args)
        return [dict(zip(("id",) + COLUMNS, row)) for row in cur.fetchall()]

    def recent(self, limit: int = 50) -> list[dict]:
        """Die letzten limit Zeilen, neueste zuerst."""
        return self._rows("SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,))

    def since(self, rowid: int, limit: int = 100) -> list[dict]:
        """Alle Zeilen mit id > rowid, aufsteigend."""
        return self._rows("SELECT * FROM requests WHERE id > ? ORDER BY id LIMIT ?", (rowid, limit))

    def max_rowid(self) -> int:
        cur = self._conn.execute("SELECT COALESCE(MAX(id), 0) FROM requests")
        return cur.fetchone()[0]

    def close(self):
        self._conn.close()
```

4. Run tests → PASS.
5. Commit: `git add src/max/telemetry tests/test_telemetry_store.py && git commit -m "max: TelemetryStore (SQLite, WAL)"`

## Task 2: TelemetryRecorder

**Files:**
- Create: `src/max/telemetry/recorder.py`
- Create: `tests/test_telemetry_recorder.py`

**TDD Steps:**
1. Write failing tests:
   - `test_latencies_measured` — begin_request, start("stt"), sleep 0.01, end("stt") → build: latency_stt_ms > 0, latency_router_ms None, latency_total_ms > 0.
   - `test_tokens_and_remote_flag` — add_tokens("router", 12), build(..., remote_needed=True) → tokens_router=12, tokens_agent=0, remote_needed=1.
   - `test_estimate_tokens` — "hallo welt" → 2, "" → 0.
   - `test_missing_stage_is_none` — no stages measured → all latencies None, total None (begin_request not called).
2. Run: `uv run pytest tests/test_telemetry_recorder.py` → FAIL.
3. Implement `src/max/telemetry/recorder.py`:

```python
"""Telemetrie-Recorder: misst Latenzen pro Stufe und sammelt Token-Zähler."""
import datetime
import time


class TelemetryRecorder:
    """Sammelt pro Anfrage: Stufen-Latenzen (ms) und Tokens pro Modell."""

    def __init__(self):
        self._stage_start: dict[str, float] = {}
        self._latencies: dict[str, float] = {}
        self._tokens = {"router": 0, "agent": 0, "remote": 0}
        self._total_start: float | None = None

    def begin_request(self):
        """Start der Total-Latenz (nach der Audio-Erfassung)."""
        self._total_start = time.monotonic()

    def start(self, stage: str):
        self._stage_start[stage] = time.monotonic()

    def end(self, stage: str):
        t0 = self._stage_start.pop(stage, None)
        if t0 is not None:
            self._latencies[stage] = (time.monotonic() - t0) * 1000.0

    def add_tokens(self, stage: str, n: int):
        if stage in self._tokens:
            self._tokens[stage] += int(n)

    def estimate_tokens(self, text: str) -> int:
        """Roh-Schätzung: Anzahl der Leerzeichen-getrennten Wörter."""
        return len((text or "").split())

    def build(self, speaker: str, text: str, agent: str, remote_needed: bool) -> dict:
        """Erzeugt das Record-Dict für den TelemetryStore."""
        total = None
        if self._total_start is not None:
            total = (time.monotonic() - self._total_start) * 1000.0
        return {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "speaker": speaker,
            "text": text,
            "agent": agent,
            "remote_needed": int(bool(remote_needed)),
            "tokens_router": self._tokens["router"],
            "tokens_agent": self._tokens["agent"],
            "tokens_remote": self._tokens["remote"],
            "latency_stt_ms": self._latencies.get("stt"),
            "latency_router_ms": self._latencies.get("router"),
            "latency_agent_ms": self._latencies.get("agent"),
            "latency_tts_ms": self._latencies.get("tts"),
            "latency_total_ms": total,
        }
```

4. Run tests → PASS.
5. Commit: `git add src/max/telemetry/recorder.py tests/test_telemetry_recorder.py && git commit -m "max: TelemetryRecorder (Stufen-Latenzen, Tokens)"`

## Task 3: AgentStore (Dashboard)

**Files:**
- Create: `src/max/dashboard/__init__.py`
- Create: `src/max/dashboard/agents.py`
- Create: `tests/test_dashboard_agents.py`

**TDD Steps:**
1. Write failing tests (tmp_path directory as agents dir):
   - `test_list_agents` — create 2 profiles → list_agents returns sorted names with `path`.
   - `test_create_conflict` — create same name twice → `AgentExistsError`.
   - `test_update` — update existing → description changed in list_agents.
   - `test_update_missing` — update nonexistent → `AgentNotFoundError`.
2. Run → FAIL.
3. Implement `src/max/dashboard/agents.py`:

```python
"""Agent-Store: liest und schreibt Agent-Profile (YAML) in config/agents/."""
from pathlib import Path

import yaml


class AgentExistsError(Exception):
    """Agent-Name existiert bereits."""


class AgentNotFoundError(Exception):
    """Agent existiert nicht."""


class AgentStore:
    def __init__(self, directory: str):
        self.directory = Path(directory)

    def list_agents(self) -> list[dict]:
        """Listet alle Profile (mit Pfad), sortiert nach Datei-Name."""
        out = []
        for f in sorted(self.directory.glob("*.yaml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data["path"] = str(f)
                out.append(data)
        return out

    def _path_for(self, name: str) -> Path:
        return self.directory / f"{name}.yaml"

    def create(self, profile: dict) -> str:
        """Erstellt ein neues Profil. Existiert es bereits: AgentExistsError."""
        name = profile["name"]
        path = self._path_for(name)
        if path.exists():
            raise AgentExistsError(name)
        path.write_text(self._to_yaml(profile), encoding="utf-8")
        return str(path)

    def update(self, name: str, profile: dict) -> str:
        """Aktualisiert ein bestehendes Profil. Existiert es nicht: AgentNotFoundError."""
        path = self._path_for(name)
        if not path.exists():
            raise AgentNotFoundError(name)
        path.write_text(self._to_yaml(profile), encoding="utf-8")
        return str(path)

    @staticmethod
    def _to_yaml(profile: dict) -> str:
        return yaml.safe_dump(profile, allow_unicode=True)
```

4. Run tests → PASS.
5. Commit: `git add src/max/dashboard tests/test_dashboard_agents.py && git commit -m "max: AgentStore (YAML-Read/Write für Dashboard)"`

## Task 4: DashboardServer

**Files:**
- Create: `src/max/dashboard/server.py`
- Create: `src/max/dashboard/__main__.py`
- Create: `tests/test_dashboard_server.py`

**TDD Steps:**
1. Write failing tests in `tests/test_dashboard_server.py` (helpers `_free_port`, `_start(tmp_path)` that builds DashboardServer with temp db + agents dir and starts in thread):
   - `test_api_requests` — seed 2 records via `server.telemetry.record(...)` → GET /api/requests returns JSON list newest-first.
   - `test_api_agents_crud` — POST /api/agents creates (200); GET /api/agents lists it; POST duplicate → 409; PUT /api/agents/demo updates (200); PUT /api/agents/ghost → 404; POST invalid JSON → 400.
   - `test_sse_streams_new_requests` — GET /events → first line `event: snapshot`; after `server.telemetry.record(...)` → within 15s receive `event: request`.
2. Run → FAIL.
3. Implement `src/max/dashboard/server.py`:

```python
"""Dashboard-Server: Telemetrie-Dashboard (Anfragen, SSE, Agent-Admin).

Endpunkte:
- GET /          → index.html (aus static/)
- GET /style.css → style.css
- GET /api/requests → JSON-Liste der letzten Anfragen (neueste zuerst)
- GET /events    → SSE-Stream: snapshot + neue Anfragen (Poll der SQLite-DB)
- GET /api/agents → JSON-Liste der Agent-Profile
- POST /api/agents → neues Profil erstellen (JSON-Body)
- PUT /api/agents/<name> → Profil aktualisieren (JSON-Body)
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from max.dashboard.agents import AgentExistsError, AgentNotFoundError, AgentStore
from max.telemetry.store import TelemetryStore

# Intervall für das Polling der Telemetrie-DB
POLL_INTERVAL = 1.0

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class DashboardHandler(BaseHTTPRequestHandler):
    """Handler mit den Endpunkten. Store/AgentStore werden auf dem httpd-Objekt injiziert."""

    def log_message(self, fmt, *args):
        pass  # ruhig bleiben — keine Request-Logs

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html")
        elif self.path == "/style.css":
            self._serve_file(os.path.join(STATIC_DIR, "style.css"), "text/css")
        elif self.path == "/api/requests":
            self._serve_json(self.server.telemetry.recent(50))
        elif self.path == "/api/agents":
            self._serve_json(self.server.agents.list_agents())
        elif self.path == "/events":
            self._serve_sse()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/agents":
            self._create_agent()
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        if self.path.startswith("/api/agents/"):
            self._update_agent(self.path[len("/api/agents/"):].strip("/"))
        else:
            self.send_response(404)
            self.end_headers()

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body)

    def _create_agent(self):
        try:
            profile = self._read_json()
            self.server.agents.create(profile)
            self._serve_json({"name": profile["name"]})
        except (json.JSONDecodeError, KeyError, TypeError):
            self.send_response(400)
            self.end_headers()
        except AgentExistsError:
            self.send_response(409)
            self.end_headers()

    def _update_agent(self, name: str):
        try:
            profile = self._read_json()
            self.server.agents.update(name, profile)
            self._serve_json({"name": name})
        except (json.JSONDecodeError, KeyError, TypeError):
            self.send_response(400)
            self.end_headers()
        except AgentNotFoundError:
            self.send_response(404)
            self.end_headers()

    def _serve_file(self, path, content_type):
        with open(path, encoding="utf-8") as f:
            body = f.read().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_json(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        snap = self.server.telemetry.recent(50)
        self.wfile.write(
            f"event: snapshot\ndata: {json.dumps(snap, ensure_ascii=False)}\n\n".encode("utf-8")
        )
        self.wfile.flush()
        last = self.server.telemetry.max_rowid()
        while True:
            time.sleep(POLL_INTERVAL)
            rows = self.server.telemetry.since(last)
            if rows:
                for row in rows:
                    self.wfile.write(
                        f"event: request\ndata: {json.dumps(row, ensure_ascii=False)}\n\n".encode("utf-8")
                    )
                self.wfile.flush()
                last = max(row["id"] for row in rows)


class DashboardServer:
    """Kapselt HTTP-Server, TelemetryStore und AgentStore."""

    def __init__(self, db_path: str, agents_dir: str):
        self.telemetry = TelemetryStore(db_path)
        self.agents = AgentStore(agents_dir)

    def _bind(self, host, port):
        httpd = ThreadingHTTPServer((host, port), DashboardHandler)
        httpd.telemetry = self.telemetry
        httpd.agents = self.agents
        return httpd

    def serve_forever(self, host: str = "127.0.0.1", port: int = 8081):
        self._bind(host, port).serve_forever()

    def start_in_thread(self, host: str = "127.0.0.1", port: int = 8081):
        """Startet den Server in einem Daemon-Thread. Liefert das httpd-Objekt."""
        httpd = self._bind(host, port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd
```

And `src/max/dashboard/__main__.py`:

```python
"""Startpunkt: python -m max.dashboard"""
import os

from max.dashboard.server import DashboardServer


def main():
    port = int(os.environ.get("MAX_DASHBOARD_PORT", "8081"))
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    server = DashboardServer(
        db_path=os.path.join(root, "data", "telemetry.db"),
        agents_dir=os.path.join(root, "config", "agents"),
    )
    server.serve_forever(port=port)


if __name__ == "__main__":
    main()
```

4. Run tests → PASS. (Tests do not hit `/` or `/style.css` — those are covered in Task 5/7.)
5. Commit: `git add src/max/dashboard/server.py src/max/dashboard/__main__.py tests/test_dashboard_server.py && git commit -m "max: DashboardServer (REST, SSE, Agent-Admin)"`

## Task 5: Dashboard Frontend

**Files:**
- Create: `src/max/dashboard/static/index.html`
- Create: `src/max/dashboard/static/style.css`
- Create: `tests/test_dashboard_frontend.py`

**TDD Steps:**
1. Write failing test `tests/test_dashboard_frontend.py` (path: 2× dirname from tests/):
   - `test_index_html` — file exists and contains: `EventSource`, `/events`, `/api/agents`, `style.css`.
   - `test_style_css` — file exists and contains `background`.
2. Run → FAIL.
3. Implement `index.html`:
   - `<section id="requests">` with `<table>` + `<tbody id="rows">`.
   - `new EventSource("/events")` with listeners `snapshot` and `request`; each adds a row via `addRow` (ts, speaker, text, agent, remote ja/nein, tokens router/agent/remote, total latency ms; null → "-").
   - `<section id="agents">`: load list via `fetch("/api/agents")`; form with name/description/keywords/capabilities (comma-separated) → POST `/api/agents` → reload list on success, alert on error.
   - Vanilla JS only, German labels.
4. Implement `style.css`: minimal dark theme (background #101418, table borders, sections).
5. Run tests → PASS.
6. Commit: `git add src/max/dashboard/static tests/test_dashboard_frontend.py && git commit -m "max: Dashboard-Frontend (Live-Tracking, Agent-Form)"`

## Task 6: Pipeline-Integration (Telemetrie + --serve-dashboard)

**Files:**
- Modify: `src/max/router/classify.py`
- Modify: `src/max/router/graph.py`
- Modify: `src/max/main.py`
- Create: `tests/test_telemetry_integration.py`

**TDD Steps:**
1. Write failing tests in `tests/test_telemetry_integration.py`:
   - `test_local_request_recorded` — build graph with `recorder` (real TelemetryRecorder), FakeClassifier(agent="ernaehrungsplaner"), MockAgentRunner, MockServer2; invoke → after finishing the request, call `recorder.build(...)` and `store.record(...)`; assert row in store has `latency_stt_ms` not None, `tokens_router` == 0 (FakeClassifier has no tokens) — actually assert `agent == "ernaehrungsplaner"`, `remote_needed == 0`, `latency_total_ms > 0`.
   - `test_recorder_failure_does_not_crash` — fake recorder whose `start`/`end` raise; graph still produces an answer.

   For wiring the recorder into `build_graph`, add an optional `recorder=None` parameter.

2. Implement `classify.py` changes:
   - `Classification` dataclass gains `tokens: int = 0`.
   - `OllamaClassifier.classify` passes `tokens=resp.get("count", 0)` to `parse_classification` (signature gains `tokens: int = 0`).

3. Implement `graph.py` changes — `build_graph(..., recorder=None)`:
   - `transcribe` node: `recorder.start("stt")` before transcribe, `recorder.end("stt")` after diarize (guard `recorder is not None`).
   - `classify` node: start/end "router" around classifier call; `recorder.add_tokens("router", c.tokens)`.
   - `respond_local` node: start/end "agent" around `runner.run`; `recorder.add_tokens("agent", recorder.estimate_tokens(result.answer))`.
   - `confirm` node on Yes: `recorder.add_tokens("remote", recorder.estimate_tokens(answer))`.

4. Implement `main.py` changes:
   - Import `TelemetryStore`, `TelemetryRecorder`, `DashboardServer`.
   - Create `recorder = TelemetryRecorder()` and `store = TelemetryStore(os.path.join(ROOT, "data", "telemetry.db"))`.
   - In the loop: `recorder.begin_request()` after `capture_audio()`; TTS wrapped with `recorder.start("tts")`/`recorder.end("tts")` around `speak()`.
   - After each request: build record via `recorder.build(speaker, text, agent, remote_needed)` and `store.record(record)` inside try/except (log on error, never crash).
   - `--serve-dashboard` argparse flag: start `DashboardServer(...).start_in_thread(port=int(os.environ.get("MAX_DASHBOARD_PORT", "8081")))`.

5. Run all tests → PASS.
6. Commit: `git add -A && git commit -m "max: Pipeline-Telemetrie + --serve-dashboard"`

## Task 7: E2E Test

**Files:**
- Create: `tests/test_dashboard_e2e.py`

**Steps:**
1. Test: start DashboardServer in thread on free port with temp db + agents dir; write a static index.html/style.css into a temp static dir? No — static files are fixed in repo. Instead:
   - `test_e2e_dashboard` — `_free_port`, start server (repo static files exist after Task 5); GET `/` → 200 and contains "EventSource"; GET `/api/requests` → 200 JSON list (empty); record a request; GET `/api/requests` → 1 row.
2. Run → PASS (needs Tasks 4+5 done).
3. Commit: `git add tests/test_dashboard_e2e.py && git commit -m "max: e2e Dashboard-Test"`

## Task 8: Final Verification

- Run full suite: `uv run pytest tests/ -q` → all green (expect 70 + new tests).
- `uv run python -m max.dashboard` smoke check (background, curl / and /api/agents, kill).
- Commit if anything touched; confirm working tree clean.

## Task List (for SDD ledger)
1. TelemetryStore
2. TelemetryRecorder
3. AgentStore
4. DashboardServer + __main__
5. Frontend
6. Pipeline-Integration + --serve-dashboard
7. E2E test
8. Final verification
