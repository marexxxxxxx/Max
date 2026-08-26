# Max Remote-PC (echt) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ersetzt `MockServer2` durch eine echte Remote-Anbindung: Server 2 als eigener HTTP-Prozess, konfigurierbares großes Modell (Ollama-Default, Generic-HTTP, Stub), zweistufiger Wake und Remote-Telemetrie.

**Architecture:** `RemoteServer2Client` spricht den Server-2-Dienst per HTTP an (stdlib `urllib`) und hat die gleiche Interface wie `MockServer2` (Duck-Typing) — der Graph braucht nur die Remote-Latenz-Messung dazu. Der Server-2-Dienst ist ein `ThreadingHTTPServer` mit `/health`, `/wake`, `/ask` und einem injizierten Modell-Backend. Wake: erst Soft-Wake per HTTP, bei Unerreichbarkeit `PowerSwitch.trigger()` + Health-Polling bis zum Timeout.

**Tech Stack:** Python 3.12, stdlib only (`urllib`, `http.server`, `threading`, `sqlite3`, `subprocess`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-max-remote-pc-design.md`

## Global Constraints

- Keine neuen Dependencies: stdlib only.
- `MockServer2` (`src/max/remote/server2.py`) bleibt unverändert.
- Telemetrie- und Client-Fehler dürfen die Pipeline nie crashen (Guard-Pattern: try/except + `print("[Max] Telemetrie-Error: ...")`).
- Ports: Server-2-Dienst Default **8090**, Ollama **11434**, Display **8080**, Dashboard **8081**.
- Fallback-Text bei unerreichbarem Server 2: **„Der Hauptrechner ist nicht erreichbar“** (exakt).
- Tests: alle offline, stdlib only; Check `uv run pytest tests/ -q`.
- Commit-Style: `max: <Beschreibung>`.
- Deutsche Docstrings/Kommentare (Codebase-Konvention).

## File Structure

```
src/max/remote/
├── server2.py      # MockServer2 (unverändert)
├── backends.py     # StubBackend, OllamaBackend, GenericHttpBackend (neu)
├── wake.py         # PowerSwitch, CommandPowerSwitch (neu)
├── service.py      # Server2Service, make_backend_from_env, python -m max.remote.service (neu)
└── client.py       # RemoteServer2Client (neu)
```

Geändert: `src/max/telemetry/store.py`, `src/max/telemetry/recorder.py`, `src/max/router/graph.py`, `src/max/main.py`, `src/max/dashboard/static/index.html`.

---

### Task 1: Modell-Backends (`src/max/remote/backends.py`)

**Files:**
- Create: `src/max/remote/backends.py`
- Test: `tests/test_remote_backends.py`

**Interfaces:**
- Consumes: nichts (neue Datei).
- Produces: `StubBackend(answer: str)`, `OllamaBackend(host, port, model, timeout)`, `GenericHttpBackend(url, headers, timeout)` — alle mit `ask(query: str) -> tuple[str, int]` (Antworttext, Token-Count).

- [ ] **Step 1: Failing Test schreiben**

`tests/test_remote_backends.py`:

```python
import json
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from max.remote.backends import GenericHttpBackend, OllamaBackend, StubBackend


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeOllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = json.dumps({"message": {"content": "Fake-Answer"}, "count": 7}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakeGenericHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = json.dumps({"answer": "Generic-Antwort", "tokens": 3}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_stub_backend():
    assert StubBackend("Pong").ask("Hallo") == ("Pong", 1)


def test_stub_backend_default():
    answer, tokens = StubBackend().ask("Hallo")
    assert tokens == len(answer.split())


def test_ollama_backend():
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), FakeOllamaHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.2)
    assert OllamaBackend("127.0.0.1", port, "test-model").ask("Hallo") == ("Fake-Answer", 7)


def test_generic_backend():
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), FakeGenericHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.2)
    assert GenericHttpBackend(f"http://127.0.0.1:{port}/model").ask("Hallo") == ("Generic-Antwort", 3)
```

- [ ] **Step 2: Test läuft und scheitert**

Run: `uv run pytest tests/test_remote_backends.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'max.remote.backends'`

- [ ] **Step 3: Minimal-Implementierung**

`src/max/remote/backends.py`:

```python
"""Modell-Backends für Server 2: Ollama (Default), Generic-HTTP, Stub."""
import json
import urllib.request


class StubBackend:
    """Feste Antwort für Dev/Tests."""

    def __init__(self, answer: str = "Antwort des großen Modells"):
        self.answer = answer

    def ask(self, query: str) -> tuple[str, int]:
        return self.answer, len(self.answer.split())


class OllamaBackend:
    """Spricht die Ollama-HTTP-API auf Server 2 an (Port 11434)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 11434, model: str = "llama3", timeout: float = 60.0):
        self.host = host
        self.port = port
        self.model = model
        self.timeout = timeout

    def ask(self, query: str) -> tuple[str, int]:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": query}],
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://{self.host}:{self.port}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["message"]["content"], int(data.get("count", 0))


class GenericHttpBackend:
    """Beliebige Model-API: POST {"query": ...} → {"answer": ..., "tokens": ...}."""

    def __init__(self, url: str, headers: dict | None = None, timeout: float = 60.0):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout

    def ask(self, query: str) -> tuple[str, int]:
        body = json.dumps({"query": query}).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json", **self.headers},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["answer"], int(data.get("tokens", 0))
```

- [ ] **Step 4: Test läuft und passt**

Run: `uv run pytest tests/test_remote_backends.py -v` → 4 PASS
Run: `uv run pytest tests/ -q` → keine Regressionen (bestehende 91 Tests grün)

- [ ] **Step 5: Commit**

```bash
git add src/max/remote/backends.py tests/test_remote_backends.py
git commit -m "max: Remote-Backends (Ollama, Generic-HTTP, Stub)"
```

---

### Task 2: Power-Switch (`src/max/remote/wake.py`)

**Files:**
- Create: `src/max/remote/wake.py`
- Test: `tests/test_remote_wake.py`

**Interfaces:**
- Consumes: nichts.
- Produces: `PowerSwitch` (abstrakt, `trigger() -> None`), `CommandPowerSwitch(command: str)` — führt einen Shell-Befehl aus.

- [ ] **Step 1: Failing Test schreiben**

`tests/test_remote_wake.py`:

```python
from max.remote.wake import CommandPowerSwitch, PowerSwitch


def test_power_switch_abstract():
    try:
        PowerSwitch().trigger()
        assert False, "trigger() muss NotImplementedError werfen"
    except NotImplementedError:
        pass


def test_command_power_switch_runs_command(tmp_path):
    marker = tmp_path / "marker"
    CommandPowerSwitch(f"touch {marker}").trigger()
    assert marker.exists()
```

- [ ] **Step 2: Test läuft und scheitert**

Run: `uv run pytest tests/test_remote_wake.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'max.remote.wake'`

- [ ] **Step 3: Minimal-Implementierung**

`src/max/remote/wake.py`:

```python
"""Abstraktes Power-Switch-Backend (hardware-agnostisch)."""
import subprocess


class PowerSwitch:
    """Schnittstelle: löst das Einschalten des Hauptrechners aus."""

    def trigger(self) -> None:
        raise NotImplementedError


class CommandPowerSwitch(PowerSwitch):
    """Führt einen externen Befehl aus (z. B. HTTP-Request an ein WLAN-Power-Switch-Gerät)."""

    def __init__(self, command: str):
        self.command = command

    def trigger(self) -> None:
        subprocess.run(self.command, shell=True)
```

- [ ] **Step 4: Test läuft und passt**

Run: `uv run pytest tests/test_remote_wake.py -v` → 2 PASS
Run: `uv run pytest tests/ -q` → keine Regressionen

- [ ] **Step 5: Commit**

```bash
git add src/max/remote/wake.py tests/test_remote_wake.py
git commit -m "max: Power-Switch-Abstraktion"
```

---

### Task 3: Server-2-Service (`src/max/remote/service.py`)

**Files:**
- Create: `src/max/remote/service.py`
- Test: `tests/test_remote_service.py`

**Interfaces:**
- Consumes: `StubBackend` / `OllamaBackend` / `GenericHttpBackend` (Task 1).
- Produces: `Server2Service(backend, host="127.0.0.1", port=8090)` mit `serve_forever()` / `start_in_thread()`; `make_backend_from_env()`; Entry-Point `python -m max.remote.service`.

- [ ] **Step 1: Failing Test schreiben**

`tests/test_remote_service.py`:

```python
import json
import socket
import time
import urllib.request

from max.remote.backends import StubBackend
from max.remote.service import Server2Service


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
        return json.loads(r.read().decode("utf-8"))


def _post(port, path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def _service():
    port = _free_port()
    Server2Service(StubBackend("Pong"), port=port).start_in_thread()
    time.sleep(0.2)
    return port


def test_health():
    port = _service()
    assert _get(port, "/health") == {"status": "ok"}


def test_wake():
    port = _service()
    assert _post(port, "/wake", {}) == {"status": "ok"}


def test_ask():
    port = _service()
    assert _post(port, "/ask", {"query": "Hallo"}) == {"answer": "Pong", "tokens": 1}
```

- [ ] **Step 2: Test läuft und scheitert**

Run: `uv run pytest tests/test_remote_service.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'max.remote.service'`

- [ ] **Step 3: Minimal-Implementierung**

`src/max/remote/service.py`:

```python
"""Server-2-Dienst: HTTP-Endpunkte für das große Modell (eigener Prozess).

Start: python -m max.remote.service
Env: MAX_REMOTE_PORT (Default 8090), MAX_REMOTE_BACKEND (ollama|http|stub),
     MAX_REMOTE_MODEL, MAX_REMOTE_MODEL_URL, MAX_OLLAMA_HOST, MAX_OLLAMA_PORT
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from max.remote.backends import GenericHttpBackend, OllamaBackend, StubBackend


class Server2Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self._serve_json({"status": "ok"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/wake":
            self._serve_json({"status": "ok"})
        elif self.path == "/ask":
            self._handle_ask()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_ask(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        answer, tokens = self.server.backend.ask(body.get("query", ""))
        self._serve_json({"answer": answer, "tokens": tokens})

    def _serve_json(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server2Service:
    """Kapselt HTTP-Server und injiziertes Modell-Backend."""

    def __init__(self, backend, host: str = "127.0.0.1", port: int = 8090):
        self.backend = backend
        self.host = host
        self.port = port

    def _bind(self):
        httpd = ThreadingHTTPServer((self.host, self.port), Server2Handler)
        httpd.backend = self.backend
        return httpd

    def serve_forever(self):
        self._bind().serve_forever()

    def start_in_thread(self):
        httpd = self._bind()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd


def make_backend_from_env():
    """Wählt das Backend via MAX_REMOTE_BACKEND (Default: Ollama)."""
    kind = os.environ.get("MAX_REMOTE_BACKEND", "ollama").lower()
    if kind == "stub":
        return StubBackend()
    if kind == "http":
        return GenericHttpBackend(os.environ.get("MAX_REMOTE_MODEL_URL", ""))
    return OllamaBackend(
        host=os.environ.get("MAX_OLLAMA_HOST", "127.0.0.1"),
        port=int(os.environ.get("MAX_OLLAMA_PORT", "11434")),
        model=os.environ.get("MAX_REMOTE_MODEL", "llama3"),
    )


def main():
    port = int(os.environ.get("MAX_REMOTE_PORT", "8090"))
    Server2Service(make_backend_from_env(), port=port).serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Test läuft und passt**

Run: `uv run pytest tests/test_remote_service.py -v` → 3 PASS
Run: `uv run pytest tests/ -q` → keine Regressionen

- [ ] **Step 5: Commit**

```bash
git add src/max/remote/service.py tests/test_remote_service.py
git commit -m "max: Server-2-Service (HTTP-Dienst)"
```

---

### Task 4: RemoteServer2Client (`src/max/remote/client.py`)

**Files:**
- Create: `src/max/remote/client.py`
- Test: `tests/test_remote_client.py`

**Interfaces:**
- Consumes: `PowerSwitch` / `CommandPowerSwitch` (Task 2); `Server2Service` + `StubBackend` (Tasks 1, 3 — für Tests).
- Produces: `RemoteServer2Client(host, port=8090, power_switch=None, timeout=60.0, wake_timeout=120.0, poll_interval=2.0)`; `wake() -> bool`; `ask(query) -> str` (Fallback-Text bei Fehler); Attribut `last_tokens: int | None` (echter Count vom Backend, sonst None).

- [ ] **Step 1: Failing Test schreiben**

`tests/test_remote_client.py`:

```python
import socket
import time

from max.remote.backends import StubBackend
from max.remote.client import RemoteServer2Client
from max.remote.service import Server2Service


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class BootOnTrigger:
    """Simuliert das Einschalten des Hauptrechners: bei trigger() kommt Server 2 up."""

    def __init__(self, port):
        self.port = port

    def trigger(self):
        Server2Service(StubBackend("Pong"), port=self.port).start_in_thread()


def test_wake_true_with_running_service():
    port = _free_port()
    Server2Service(StubBackend("Pong"), port=port).start_in_thread()
    time.sleep(0.2)
    assert RemoteServer2Client("127.0.0.1", port).wake() is True


def test_ask_returns_answer_and_tokens():
    port = _free_port()
    Server2Service(StubBackend("Pong"), port=port).start_in_thread()
    time.sleep(0.2)
    client = RemoteServer2Client("127.0.0.1", port)
    assert client.ask("Hallo") == "Pong"
    assert client.last_tokens == 1


def test_wake_false_without_power_switch():
    port = _free_port()  # kein Service auf diesem Port
    client = RemoteServer2Client("127.0.0.1", port, wake_timeout=0.2, poll_interval=0.1)
    assert client.wake() is False


def test_ask_fallback_when_unreachable():
    port = _free_port()
    client = RemoteServer2Client("127.0.0.1", port)
    assert client.ask("Hallo") == "Der Hauptrechner ist nicht erreichbar"


def test_wake_with_power_switch():
    port = _free_port()
    client = RemoteServer2Client(
        "127.0.0.1", port,
        power_switch=BootOnTrigger(port),
        wake_timeout=10.0, poll_interval=0.1,
    )
    assert client.wake() is True
```

- [ ] **Step 2: Test läuft und scheitert**

Run: `uv run pytest tests/test_remote_client.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'max.remote.client'`

- [ ] **Step 3: Minimal-Implementierung**

`src/max/remote/client.py`:

```python
"""RemoteServer2Client: spricht Server 2 per HTTP an (gleiche Interface wie MockServer2)."""
import json
import time
import urllib.request


class RemoteServer2Client:
    FALLBACK = "Der Hauptrechner ist nicht erreichbar"

    def __init__(self, host: str, port: int = 8090, power_switch=None,
                 timeout: float = 60.0, wake_timeout: float = 120.0,
                 poll_interval: float = 2.0):
        self.host = host
        self.port = port
        self.power_switch = power_switch
        self.timeout = timeout
        self.wake_timeout = wake_timeout
        self.poll_interval = poll_interval
        self.last_tokens: int | None = None

    def _url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    def _post_json(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self._url(path),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _get_json(self, path: str) -> dict:
        with urllib.request.urlopen(self._url(path), timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def wake(self) -> bool:
        # 1. Soft-Wake per HTTP
        try:
            self._post_json("/wake", {})
            return True
        except Exception:
            pass
        # 2. Power-Switch + Health-Polling
        if self.power_switch is None:
            return False
        self.power_switch.trigger()
        deadline = time.monotonic() + self.wake_timeout
        last_print = 0.0
        while time.monotonic() < deadline:
            try:
                self._get_json("/health")
                return True
            except Exception:
                now = time.monotonic()
                if now - last_print >= 10:
                    print("[Max] Warte auf Server 2 ...")
                    last_print = now
                time.sleep(self.poll_interval)
        return False

    def ask(self, query: str) -> str:
        try:
            data = self._post_json("/ask", {"query": query})
            self.last_tokens = data.get("tokens")
            return data.get("answer", "")
        except Exception:
            self.last_tokens = None
            return self.FALLBACK
```

- [ ] **Step 4: Test läuft und passt**

Run: `uv run pytest tests/test_remote_client.py -v` → 5 PASS
Run: `uv run pytest tests/ -q` → keine Regressionen

- [ ] **Step 5: Commit**

```bash
git add src/max/remote/client.py tests/test_remote_client.py
git commit -m "max: RemoteServer2Client (Wake + ask)"
```

---

### Task 5: Telemetrie-Erweiterung (`store`, `recorder`, `graph`)

**Files:**
- Modify: `src/max/telemetry/store.py`
- Modify: `src/max/telemetry/recorder.py`
- Modify: `src/max/router/graph.py` (confirm-Node)
- Test: `tests/test_telemetry_remote.py`

**Interfaces:**
- Consumes: nichts Neues.
- Produces: neue Spalte `latency_remote_ms` (DB + Record-Dict); `confirm`-Node misst die remote-Stage und nutzt den echten Token-Count (`server2.last_tokens`), falls vorhanden, sonst Whitespace-Split-Estimate.

- [ ] **Step 1: Failing Test schreiben**

`tests/test_telemetry_remote.py`:

```python
import sqlite3

from max.telemetry.recorder import TelemetryRecorder
from max.telemetry.store import TelemetryStore


def test_store_migration_old_schema(tmp_path):
    path = str(tmp_path / "telemetry.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE requests (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts TEXT, speaker TEXT, text TEXT, agent TEXT,"
        "remote_needed INTEGER,"
        "tokens_router INTEGER, tokens_agent INTEGER, tokens_remote INTEGER,"
        "latency_stt_ms REAL, latency_router_ms REAL,"
        "latency_agent_ms REAL, latency_tts_ms REAL, latency_total_ms REAL)"
    )
    conn.commit()
    conn.close()
    store = TelemetryStore(path)
    rid = store.record({"speaker": "Alex", "text": "hallo"})
    row = store.recent(1)[0]
    assert row["id"] == rid
    assert row["latency_remote_ms"] is None
    store.close()


def test_recorder_remote_latency():
    r = TelemetryRecorder()
    r.begin_request()
    r.start("remote")
    r.end("remote")
    rec = r.build("Alex", "Testfrage", "", True)
    assert rec["latency_remote_ms"] is not None
```

- [ ] **Step 2: Test läuft und scheitert**

Run: `uv run pytest tests/test_telemetry_remote.py -v`
Expected: FAIL (KeyError bzw. fehlende Spalte / KeyError "latency_remote_ms")

- [ ] **Step 3: Implementierung**

`src/max/telemetry/store.py`:

- `COLUMNS` bekommt zwischen `latency_tts_ms` und `latency_total_ms` die neue Spalte:

```python
COLUMNS = (
    "ts", "speaker", "text", "agent", "remote_needed",
    "tokens_router", "tokens_agent", "tokens_remote",
    "latency_stt_ms", "latency_router_ms",
    "latency_agent_ms", "latency_tts_ms", "latency_remote_ms", "latency_total_ms",
)
```

- `CREATE TABLE` erhält `latency_remote_ms REAL` (zwischen `latency_tts_ms` und `latency_total_ms`) und danach das fehlertolerante Nachlegen für bestehende DBs:

```python
        # Bestehende DBs: Spalte fehlertolerant nachlegen
        try:
            self._conn.execute("ALTER TABLE requests ADD COLUMN latency_remote_ms REAL")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
```

- `record()`: die INSERT-Liste erhält `latency_remote_ms` (insgesamt 15 Spalten, `VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).

`src/max/telemetry/recorder.py` — in `build()` zwischen `latency_tts_ms` und `latency_total_ms`:

```python
"latency_remote_ms": self._latencies.get("remote"),
```

`src/max/router/graph.py` — `confirm`-Node:

```python
def confirm(state):
    # Bestätigungsrunde: „Ja“ schaltet Server 2 ein, sonst lokal bleiben
    if is_confirmation(state.get("confirmation") or ""):
        _start("remote")
        server2.wake()
        answer = server2.ask(state.get("query", ""))
        _end("remote")
        tokens = getattr(server2, "last_tokens", None)
        if tokens is None:
            _tel_tokens("remote", answer)
        else:
            _add_tokens("remote", tokens)
        return {"answer": answer, "awaiting_confirmation": False}
    return {"answer": "Alles klar, dann bleibe ich lokal.", "awaiting_confirmation": False}
```

(`getattr` mit Default None: `MockServer2` hat kein `last_tokens` → Schätzung wie bisher.)

- [ ] **Step 4: Test läuft und passt**

Run: `uv run pytest tests/test_telemetry_remote.py -v` → 2 PASS
Run: `uv run pytest tests/ -q` → keine Regressionen (alle 91 bestehenden Tests grün)

- [ ] **Step 5: Commit**

```bash
git add src/max/telemetry/store.py src/max/telemetry/recorder.py src/max/router/graph.py tests/test_telemetry_remote.py
git commit -m "max: Telemetrie-Erweiterung (latency_remote_ms)"
```

---

### Task 6: main.py-Wiring

**Files:**
- Modify: `src/max/main.py`
- Test: `tests/test_main_wiring.py`

**Interfaces:**
- Consumes: `RemoteServer2Client` (Task 4), `CommandPowerSwitch` (Task 2), `MockServer2`.
- Produces: `make_server2(env=None)` — liefert bei gesetztem `MAX_REMOTE_HOST` einen `RemoteServer2Client`, sonst `MockServer2`; `main()` nutzt diese Funktion.

- [ ] **Step 1: Failing Test schreiben**

`tests/test_main_wiring.py`:

```python
from max.main import make_server2
from max.remote.client import RemoteServer2Client
from max.remote.server2 import MockServer2
from max.remote.wake import CommandPowerSwitch


def test_mock_by_default():
    assert isinstance(make_server2({}), MockServer2)


def test_remote_client_from_env():
    s2 = make_server2({"MAX_REMOTE_HOST": "10.0.0.5", "MAX_REMOTE_PORT": "9000"})
    assert isinstance(s2, RemoteServer2Client)
    assert s2.host == "10.0.0.5"
    assert s2.port == 9000


def test_power_switch_from_env():
    s2 = make_server2({
        "MAX_REMOTE_HOST": "10.0.0.5",
        "MAX_POWER_SWITCH_CMD": "curl http://switch/wake",
    })
    assert isinstance(s2.power_switch, CommandPowerSwitch)


def test_no_power_switch_without_env():
    s2 = make_server2({"MAX_REMOTE_HOST": "10.0.0.5"})
    assert s2.power_switch is None
```

- [ ] **Step 2: Test läuft und scheitert**

Run: `uv run pytest tests/test_main_wiring.py -v`
Expected: FAIL mit `ImportError: cannot import name 'make_server2'`

- [ ] **Step 3: Implementierung**

In `src/max/main.py`, neue Funktion vor `main()`:

```python
def make_server2(env=None):
    """RemoteServer2Client wenn MAX_REMOTE_HOST gesetzt, sonst MockServer2 (Dev-Default)."""
    env = env if env is not None else os.environ
    host = env.get("MAX_REMOTE_HOST", "")
    if not host:
        return MockServer2()
    from max.remote.client import RemoteServer2Client
    from max.remote.wake import CommandPowerSwitch
    power = CommandPowerSwitch(env["MAX_POWER_SWITCH_CMD"]) if env.get("MAX_POWER_SWITCH_CMD") else None
    return RemoteServer2Client(
        host=host,
        port=int(env.get("MAX_REMOTE_PORT", "8090")),
        power_switch=power,
        timeout=float(env.get("MAX_REMOTE_TIMEOUT", "60")),
        wake_timeout=float(env.get("MAX_REMOTE_WAKE_TIMEOUT", "120")),
    )
```

In `main()`: `MockServer2()` ersetzen durch `make_server2()` (der Import `from max.remote.server2 import MockServer2` bleibt).

- [ ] **Step 4: Test läuft und passt**

Run: `uv run pytest tests/test_main_wiring.py -v` → 4 PASS
Run: `uv run pytest tests/ -q` → keine Regressionen

- [ ] **Step 5: Commit**

```bash
git add src/max/main.py tests/test_main_wiring.py
git commit -m "max: main.py-Wiring (MAX_REMOTE_HOST)"
```

---

### Task 7: Dashboard-Frontend (Remote-Latenz-Spalte)

**Files:**
- Modify: `src/max/dashboard/static/index.html`
- Test: `tests/test_dashboard_frontend.py` (Test anhängen)

**Interfaces:**
- Consumes: Key `latency_remote_ms` (Task 5).
- Produces: neue Tabelle-Spalte „Remote-Latenz“.

- [ ] **Step 1: Failing Test schreiben** (an `tests/test_dashboard_frontend.py` anhängen):

```python
from pathlib import Path


def test_remote_latency_column():
    text = Path(__file__).parent.parent / "src" / "max" / "dashboard" / "static" / "index.html"
    text = text.read_text(encoding="utf-8")
    assert "latency_remote_ms" in text
    assert "Remote-Latenz" in text
```

- [ ] **Step 2: Test läuft und scheitert**

Run: `uv run pytest tests/test_dashboard_frontend.py -v`
Expected: FAIL (AssertionError)

- [ ] **Step 3: Implementierung** in `index.html`:

Tabelle-Header — nach `<th>Latenz</th>`:

```html
          <th>Remote-Latenz</th>
```

`addRow` — nach der Latenz-Variablenberechnung:

```javascript
      var remote = row.latency_remote_ms == null ? "-" : Math.round(row.latency_remote_ms) + " ms";
```

und in `tr.innerHTML` nach dem Latenz-Zellend `- td`:

```javascript
        "<td>" + remote + "</td>";
```

- [ ] **Step 4: Test läuft und passt**

Run: `uv run pytest tests/test_dashboard_frontend.py -v` → alle PASS (inkl. bestehender Frontend-Tests)

- [ ] **Step 5: Commit**

```bash
git add src/max/dashboard/static/index.html tests/test_dashboard_frontend.py
git commit -m "max: Dashboard-Frontend (Remote-Latenz-Spalte)"
```

---

### Task 8: E2E-Test (Graph + Client + Service + Telemetrie)

**Files:**
- Create: `tests/test_remote_e2e.py`

**Interfaces:**
- Consumes: alles aus Tasks 1–6.
- Produces: Offline-E2E-Test der kompletten Remote-Pfad-Logik.

- [ ] **Step 1: Test schreiben**

`tests/test_remote_e2e.py`:

```python
import socket
import time

from max.agents.runner import MockAgentRunner
from max.remote.backends import StubBackend
from max.remote.client import RemoteServer2Client
from max.remote.service import Server2Service
from max.router.graph import build_graph
from max.telemetry.recorder import TelemetryRecorder
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_remote_e2e():
    port = _free_port()
    Server2Service(StubBackend("Stub-Antwort"), port=port).start_in_thread()
    time.sleep(0.2)
    client = RemoteServer2Client("127.0.0.1", port)
    recorder = TelemetryRecorder()
    g = build_graph(
        FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
        FakeClassifier(remote_needed=True),
        [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}],
        MockAgentRunner(),
        client,
        recorder=recorder,
    )
    recorder.begin_request()
    first = g.invoke({"audio": b"xx"})
    assert first["awaiting_confirmation"] is True
    second = g.invoke({"confirmation": "Ja", "query": first["query"]})
    assert second["answer"] == "Stub-Antwort"
    record = recorder.build("Alex", "Testfrage", "", True)
    assert record["latency_remote_ms"] is not None
    assert record["tokens_remote"] == 1
```

- [ ] **Step 2: Test läuft und passt**

Run: `uv run pytest tests/test_remote_e2e.py -v` → 1 PASS
Run: `uv run pytest tests/ -q` → komplette Suite grün (alle bestehenden + neue Tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_remote_e2e.py
git commit -m "max: E2E-Test (Remote-PC)"
```

---

## Self-Review

1. **Spec-Abdeckung:**
   - HTTP Request/Response (Abschnitt 2) → Tasks 3, 4 ✓
   - Zweistufiger Wake mit Power-Switch + Health-Polling, Timeout 120 s (Abschnitt 4) → Tasks 2, 4 ✓
   - Konfigurierbares Modell: Ollama-Default, Generic-HTTP, Stub (Abschnitt 2/5) → Tasks 1, 3 ✓
   - Telemetrie `latency_remote_ms` + `tokens_remote`, Dashboard-Spalte (Abschnitt 7) → Tasks 5, 7 ✓
   - Dev/Tests lokale 2-Prozess-Lösung, Produktion via `MAX_REMOTE_HOST` (Abschnitt 2) → Tasks 4, 6 ✓
   - Fehlerbehandlung: Fallback-Text, kein Crash, Power-Switch optional (Abschnitt 8) → Tasks 4, 5 ✓
   - `MockServer2` unverändert (Abschnitt 3) → global constraint ✓
2. **Keine Placeholders:** alle Steps enthalten vollständigen Code.
3. **Typ-Konsistenz:** `ask(query) -> tuple[str, int]` (Backends), `ask(query) -> str` + `last_tokens` (Client), `latency_remote_ms` in COLUMNS, Record-Dict und Frontend — konsistent über alle Tasks.
