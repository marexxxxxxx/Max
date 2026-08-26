"""E2E-Test: Dashboard-Server mit echten statischen Dateien und Telemetrie-DB."""
import json
import os
import socket
import urllib.request

from max.dashboard.server import DashboardServer


def _free_port():
    """Findet einen freien Port (Socket an Port 0 binden)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_e2e_dashboard(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), "agents"), exist_ok=True)
    server = DashboardServer(
        db_path=str(tmp_path / "telemetry.db"),
        agents_dir=str(tmp_path / "agents"),
    )
    port = _free_port()
    server.start_in_thread(port=port)
    base = f"http://127.0.0.1:{port}"

    # Frontend: index.html wird serviert
    with urllib.request.urlopen(base + "/", timeout=5) as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert "EventSource" in body
        assert "style.css" in body

    # Noch keine Anfragen
    with urllib.request.urlopen(base + "/api/requests", timeout=5) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8")) == []

    # Eine Anfrage wird über den Telemetrie-Store geschrieben
    server.telemetry.record(
        {
            "speaker": "Alex",
            "text": "E2E",
            "agent": "demo",
            "remote_needed": True,
            "latency_total_ms": 42.0,
        }
    )

    with urllib.request.urlopen(base + "/api/requests", timeout=5) as resp:
        assert resp.status == 200
        rows = json.loads(resp.read().decode("utf-8"))
        assert len(rows) == 1
        assert rows[0]["text"] == "E2E"
        assert rows[0]["remote_needed"] == 1

    # Agenten-Liste (noch leer)
    with urllib.request.urlopen(base + "/api/agents", timeout=5) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8")) == []
