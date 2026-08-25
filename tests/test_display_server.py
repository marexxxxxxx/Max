import json
import socket
import time
import urllib.request

from max.display.server import DisplayServer


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _fake_weather(lat, lon):
    return {"hourly": {"temperature_2m": [20.0], "weather_code": [0]}}


def test_api_cards(tmp_path):
    cal = tmp_path / "calendar.json"
    cal.write_text('{"events": [{"date": "2026-08-25", "title": "Test"}]}', encoding="utf-8")
    port = _free_port()
    httpd = DisplayServer(str(tmp_path), calendar_path=str(cal), fetcher=_fake_weather).start_in_thread(port=port)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/cards", timeout=5) as r:
            cards = json.loads(r.read().decode("utf-8"))
        types = {c["type"] for c in cards}
        assert {"clock", "weather", "calendar"} <= types
    finally:
        httpd.shutdown()


def test_sse_event_on_card_change(tmp_path):
    port = _free_port()
    httpd = DisplayServer(str(tmp_path), fetcher=_fake_weather).start_in_thread(port=port)
    try:
        request = urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=20)
        (tmp_path / "agent.json").write_text(
            json.dumps(
                {
                    "agent": "agent",
                    "title": "T",
                    "type": "generic",
                    "data": {"x": 1},
                    "updated_at": "2026-08-25T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        line = ""
        deadline = time.time() + 15
        while time.time() < deadline:
            line = request.readline().decode("utf-8").rstrip("\n")
            if line == "event: card":
                break
        assert line == "event: card"
    finally:
        httpd.shutdown()


def test_weather_cache_ttl(tmp_path):
    calls = {"n": 0}

    def fake(lat, lon):
        calls["n"] += 1
        return {"hourly": {"temperature_2m": [20.0], "weather_code": [0]}}

    server = DisplayServer(str(tmp_path), fetcher=fake, weather_ttl=3600)
    server._refresh_snapshot()
    server._refresh_snapshot()
    assert calls["n"] == 1
