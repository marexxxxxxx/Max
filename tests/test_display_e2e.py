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


def test_display_e2e(tmp_path):
    cal = tmp_path / "calendar.json"
    cal.write_text('{"events": [{"date": "2026-08-25", "title": "Test"}]}', encoding="utf-8")
    port = _free_port()
    httpd = DisplayServer(str(tmp_path), calendar_path=str(cal), fetcher=_fake_weather).start_in_thread(port=port)
    try:
        # 1) Routine-Cards im API
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/cards", timeout=5) as r:
            cards = json.loads(r.read().decode("utf-8"))
        types = [c["type"] for c in cards]
        assert "clock" in types and "weather" in types and "calendar" in types

        # 2) Agent-Card erscheint nach Polling
        (tmp_path / "e2e.json").write_text(
            json.dumps(
                {
                    "agent": "e2e",
                    "title": "E2E",
                    "type": "generic",
                    "data": {"x": "y"},
                    "updated_at": "2026-08-25T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        found = False
        deadline = time.time() + 15
        while time.time() < deadline and not found:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/cards", timeout=5) as r:
                cards = json.loads(r.read().decode("utf-8"))
            if any(c["agent"] == "e2e" for c in cards):
                found = True
            time.sleep(0.5)
        assert found
    finally:
        httpd.shutdown()
