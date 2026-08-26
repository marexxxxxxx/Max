"""Tests für den Dashboard-Server (REST, SSE, Agent-Admin)."""
import json
import os
import socket
import time
import urllib.request

from max.dashboard.server import DashboardServer


def _free_port():
    """Findet einen freien Port (Socket an Port 0 binden)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start(tmp_path):
    """Startet DashboardServer mit temporärer DB und Agenten-Verzeichnis in einem Thread."""
    os.makedirs(os.path.join(str(tmp_path), "agents"), exist_ok=True)
    server = DashboardServer(
        db_path=str(tmp_path / "telemetry.db"),
        agents_dir=str(tmp_path / "agents"),
    )
    port = _free_port()
    server.start_in_thread(port=port)
    return server, port


def _request(method, url, body=None):
    """Macht eine HTTP-Anfrage und liefert (Code, Body-Text)."""
    req = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def test_api_requests(tmp_path):
    server, port = _start(tmp_path)
    base = f"http://127.0.0.1:{port}"
    server.telemetry.record({"speaker": "max", "text": "Erste", "agent": "agent"})
    server.telemetry.record({"speaker": "max", "text": "Zweite", "agent": "agent"})
    code, body = _request("GET", base + "/api/requests")
    assert code == 200
    rows = json.loads(body)
    assert [r["text"] for r in rows] == ["Zweite", "Erste"]


def test_api_agents_crud(tmp_path):
    server, port = _start(tmp_path)
    base = f"http://127.0.0.1:{port}"

    code, _ = _request("POST", base + "/api/agents", b'{"name": "demo", "description": "Demo"}')
    assert code == 200

    code, body = _request("GET", base + "/api/agents")
    assert code == 200
    assert [a["name"] for a in json.loads(body)] == ["demo"]

    code, _ = _request("POST", base + "/api/agents", b'{"name": "demo", "description": "Nochmal"}')
    assert code == 409

    code, _ = _request("PUT", base + "/api/agents/demo", b'{"name": "demo", "description": "neu"}')
    assert code == 200

    code, _ = _request("PUT", base + "/api/agents/ghost", b'{"name": "ghost", "description": "x"}')
    assert code == 404

    code, _ = _request("POST", base + "/api/agents", b"{nicht-json")
    assert code == 400


def test_sse_streams_new_requests(tmp_path):
    server, port = _start(tmp_path)
    server.telemetry.record({"speaker": "max", "text": "Alt", "agent": "agent"})

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=15) as resp:
        first = resp.readline().decode("utf-8").rstrip("\n")
        assert first == "event: snapshot"

        # Kurze Pause, damit der Handler die Basis-Rowid bereits festgelegt hat
        time.sleep(0.1)
        server.telemetry.record({"speaker": "max", "text": "Neu", "agent": "agent"})

        deadline = time.time() + 15
        received = False
        try:
            while time.time() < deadline:
                line = resp.readline().decode("utf-8").rstrip("\n")
                if line == "event: request":
                    received = True
                    break
        except TimeoutError:
            pass
        assert received


class FakeWfile:
    def __init__(self, broken=False):
        self.chunks = []
        self.broken = broken

    def write(self, data):
        if self.broken:
            raise BrokenPipeError
        self.chunks.append(data)

    def flush(self):
        pass


def _handler(tmp_path, broken=False):
    import types
    from max.dashboard.server import DashboardHandler
    from max.telemetry.store import TelemetryStore
    store = TelemetryStore(str(tmp_path / "t.db"))
    server = types.SimpleNamespace(telemetry=store)
    h = object.__new__(DashboardHandler)
    h.server = server
    h.wfile = FakeWfile(broken)
    return h, store


def test_poll_once_keepalive(monkeypatch, tmp_path):
    monkeypatch.setattr("max.dashboard.server.time.sleep", lambda s: None)
    h, store = _handler(tmp_path)
    store.record({"speaker": "A", "text": "alt", "agent": "x"})
    last = store.max_rowid()
    result = h._poll_once(last)
    assert result == last
    assert b": keepalive\n\n" in b"".join(h.wfile.chunks)


def test_poll_once_new_rows(monkeypatch, tmp_path):
    monkeypatch.setattr("max.dashboard.server.time.sleep", lambda s: None)
    h, store = _handler(tmp_path)
    store.record({"speaker": "A", "text": "alt", "agent": "x"})
    last = store.max_rowid()
    store.record({"speaker": "B", "text": "neu", "agent": "y"})
    result = h._poll_once(last)
    assert result == last + 1
    joined = b"".join(h.wfile.chunks)
    assert b"event: request" in joined and b"neu" in joined


def test_poll_once_disconnect(monkeypatch, tmp_path):
    monkeypatch.setattr("max.dashboard.server.time.sleep", lambda s: None)
    h, store = _handler(tmp_path, broken=True)
    store.record({"speaker": "A", "text": "alt", "agent": "x"})
    assert h._poll_once(store.max_rowid()) is None
