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


def test_service_custom_host():
    """Service honoriert einen expliziten Bind-Host (0.0.0.0) und ist erreichbar."""
    port = _free_port()
    Server2Service(StubBackend("Pong"), host="0.0.0.0", port=port).start_in_thread()
    time.sleep(0.2)
    assert _get(port, "/health") == {"status": "ok"}
