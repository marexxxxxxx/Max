# Max Smart Mirror (Subprojekt C) — Implementation Plan

**Objective:** Smart Mirror: Max serviert eine lokale Web-Seite, die Standard-Cards (Uhrzeit, Wetter, Kalender) und domänenspezifische Cards der Fach-Agenten zeigt. Update-Mechanik: Mischform — Routine-Daten per Polling, Agent-Pushes live per SSE.

**Spec:** docs/superpowers/specs/2026-08-25-max-smart-mirror-design.md (commit 2a21464)

**Repo:** /home/user/max — Python 3.12 (uv), Tests in tests/ mit pytest.

## File Structure

Neu:
- src/max/display/__init__.py
- src/max/display/cards.py — Card-Validierung + CardStore (dateibasiertes Polling)
- src/max/display/providers.py — Standard-Cards: Uhrzeit, Wetter (open-meteo), Kalender
- src/max/display/server.py — DisplayServer: http.server, /api/cards, /events (SSE), Polling-Thread
- src/max/display/__main__.py — Entry-Point: python -m max.display
- src/max/display/static/index.html — Frontend (vanilla JS, EventSource)
- src/max/display/static/style.css — Dark Theme
- config/calendar.json — lokale Kalenderdaten (Beispiel)
- tests/test_display_cards.py
- tests/test_display_providers.py
- tests/test_display_server.py
- tests/test_display_frontend.py
- tests/test_agent_cards.py
- tests/test_display_e2e.py

Änderungen:
- src/max/agents/runner.py — build_task_message(task, memory_context, card_path=None), _resolve_path, OpencodeRunner.run
- src/max/agents/nutrition.py — card_path im Profil
- config/opencode/ernaehrungsplaner.prompt.md — Display-Card-Sektion
- src/max/main.py — Flag --serve-display

## Global Constraints

- Keine neuen Python-Dependencies (stdlib: http.server, urllib.request, json, threading, time, socket)
- Offline-Tests: kein Netzwerk, kein GPU, kein Mikrofon. Wetter-Fetcher injectable.
- Strings und Kommentare auf Deutsch
- Nur Localhost-Bind (127.0.0.1), Port via MAX_DISPLAY_PORT (Default 8080)
- Fehler-Toleranz: Wetter/Kalender-Fehler → Card fehlt, kein Crash
- data/ bleibt gitignored (Card-Verzeichnis)
- MCP-Server (extra Fenster): NUR reserviert, nicht implementiert

## Task 1: Card-Modul (cards.py)

Files:
- Create: src/max/display/__init__.py (leer)
- Create: src/max/display/cards.py
- Create: tests/test_display_cards.py

Step 1 — Failing test (tests/test_display_cards.py):

```python
import json

from max.display.cards import CardStore, validate_card


def test_validate_card_ok():
    card = {
        "agent": "test",
        "title": "Titel",
        "type": "generic",
        "data": {"foo": "bar"},
        "updated_at": "2026-08-25T12:00:00+00:00",
    }
    assert validate_card(card) is card


def test_validate_card_rejects_missing_fields():
    assert validate_card({"agent": "test"}) is None
    assert validate_card({"agent": "test", "title": "T"}) is None


def test_validate_card_rejects_bad_type():
    assert validate_card(
        {
            "agent": "a",
            "title": "T",
            "type": "unknown",
            "data": {},
            "updated_at": "2026-08-25T12:00:00+00:00",
        }
    ) is None


def test_card_store_load_and_poll(tmp_path):
    store = CardStore(str(tmp_path))
    assert store.load_all() == []
    (tmp_path / "agent1.json").write_text(
        json.dumps(
            {
                "agent": "agent1",
                "title": "T1",
                "type": "generic",
                "data": {"x": 1},
                "updated_at": "2026-08-25T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    cards = store.load_all()
    assert len(cards) == 1
    assert cards[0]["agent"] == "agent1"
    # Erster Poll: neue Cards werden erkannt
    changed = store.poll()
    assert len(changed) == 1
    # Zweiter Poll: keine Änderung
    assert store.poll() == []
```

Step 2 — Run and verify failure:
`cd /home/user/max && uv run pytest tests/test_display_cards.py -v` → FAIL (Modul fehlt)

Step 3 — Implement src/max/display/cards.py:

```python
"""Card-Modul: Validierung und dateibasiertes Polling von Agent-Cards.

Fach-Agenten schreiben ihre Cards als JSON-Dateien in ein gemeinsames
Verzeichnis. Der Display-Server pollt dieses Verzeichnis und streamt
Änderungen per SSE.
"""
import json
import os

ALLOWED_TYPES = ("meal", "weather", "calendar", "clock", "generic")


def validate_card(raw: dict) -> dict | None:
    """Validiert eine Card. Gibt das Original zurück oder None bei Fehlern."""
    if not isinstance(raw, dict):
        return None
    for field in ("agent", "title", "type", "data", "updated_at"):
        if field not in raw:
            return None
    if raw["type"] not in ALLOWED_TYPES:
        return None
    if not isinstance(raw["data"], dict):
        return None
    return raw


class CardStore:
    """Liest Cards aus einem Verzeichnis und erkennt Änderungen per Datei-Mtime.

    poll() liefert alle Cards, die seit dem letzten Poll neu oder geändert wurden.
    """

    def __init__(self, directory: str):
        self.directory = directory
        self._last_seen: dict[str, float] = {}

    def _read_card(self, name: str) -> dict | None:
        path = os.path.join(self.directory, name)
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            card = validate_card(raw)
        except (json.JSONDecodeError, OSError):
            return None
        if card is None:
            return None
        card["_file"] = name
        return card

    def load_all(self) -> list[dict]:
        """Liest alle gültigen Cards aus dem Verzeichnis (sortiert)."""
        cards = []
        for name in sorted(os.listdir(self.directory)):
            if not name.endswith(".json"):
                continue
            card = self._read_card(name)
            if card is not None:
                cards.append(card)
        return cards

    def poll(self) -> list[dict]:
        """Erkennt neue/geänderte Cards anhand der Dateimtimes."""
        changed = []
        for name in sorted(os.listdir(self.directory)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.directory, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime > self._last_seen.get(name, 0.0):
                card = self._read_card(name)
                if card is None:
                    continue
                self._last_seen[name] = mtime
                changed.append(card)
        # gelöschte Dateien aus dem Mtime-Speicher entfernen
        existing = set(os.listdir(self.directory))
        self._last_seen = {k: v for k, v in self._last_seen.items() if k in existing}
        return changed
```

Step 4 — Run and verify pass:
`cd /home/user/max && uv run pytest tests/test_display_cards.py -v` → PASS

Step 5 — Commit:
`git add src/max/display/__init__.py src/max/display/cards.py tests/test_display_cards.py && git commit -m "max: display card store"`

## Task 2: Standard-Card-Provider (providers.py)

Files:
- Create: src/max/display/providers.py
- Create: tests/test_display_providers.py

Step 1 — Failing tests (tests/test_display_providers.py):

```python
from datetime import datetime

from max.display.providers import calendar_card, clock_card, weather_card


def test_clock_card_shape():
    card = clock_card()
    assert card["agent"] == "display"
    assert card["type"] == "clock"
    datetime.fromisoformat(card["data"]["time"])


def test_weather_card_with_fake_fetcher():
    def fake_fetch(lat, lon):
        return {"hourly": {"temperature_2m": [21.5], "weather_code": [1]}}
    card = weather_card(fake_fetch, 52.52, 13.405)
    assert card["type"] == "weather"
    assert card["data"]["temperature"] == "21,5 °C"
    assert card["data"]["condition"]


def test_weather_card_returns_none_on_error():
    def broken_fetch(lat, lon):
        raise RuntimeError("offline")
    assert weather_card(broken_fetch, 52.52, 13.405) is None


def test_calendar_card(tmp_path):
    path = tmp_path / "calendar.json"
    path.write_text('{"events": [{"date": "2026-08-25", "title": "Zahnarzt"}]}', encoding="utf-8")
    card = calendar_card(str(path))
    assert card["type"] == "calendar"
    assert len(card["data"]["events"]) == 1


def test_calendar_card_missing_file():
    assert calendar_card("/nonexistent/calendar.json") is None


def test_calendar_card_empty():
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "calendar.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"events": []}, f)
        assert calendar_card(path) is None
```

Note: tests/test_display_providers.py needs `import os` at the top.

Step 2 — Run and verify failure → FAIL (Modul fehlt)

Step 3 — Implement src/max/display/providers.py:

```python
"""Standard-Cards für den Smart Mirror: Uhrzeit, Wetter, Kalender.

Wetter kommt von open-meteo (free, ohne API-Key). Alle Provider sind
best-effort: bei Fehlern geben sie None zurück, statt zu crashen.
"""
import datetime
import json
import urllib.request

# Default-Standort (Berlin)
DEFAULT_LAT = 52.52
DEFAULT_LON = 13.405

# open-meteo weather_code → deutsche Beschreibung
WEATHER_TEXT = {
    0: "klar",
    1: "meist klar",
    2: "leicht bewölkt",
    3: "bedeckt",
    45: "Nebel",
    48: "nebelfrost",
    51: "Nieselregen",
    53: "Nieselregen",
    55: "Nieselregen",
    61: "leichter Regen",
    63: "Regen",
    65: "starker Regen",
    71: "leichter Schnee",
    73: "Schnee",
    77: "starker Schnee",
    80: "Regenschauer",
    81: "Regenschauer",
    82: "starke Regenschauer",
    95: "Gewitter",
    96: "Gewitter mit Hagel",
    99: "starkes Gewitter",
}


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _format_temperature(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + " °C"


def clock_card() -> dict:
    """Uhrzeit-Card (aktuelle Zeit, ISO-Format)."""
    return {
        "agent": "display",
        "title": "Zeit",
        "type": "clock",
        "data": {"time": _now_iso()},
        "updated_at": _now_iso(),
    }


def open_meteo_fetcher(lat: float, lon: float) -> dict:
    """Holt aktuelle Wetterdaten von open-meteo (ohne API-Key)."""
    url = (
        "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m,weather_code".format(lat=lat, lon=lon)
    )
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def weather_card(fetcher, lat: float, lon: float) -> dict | None:
    """Wetter-Card aus einem Fetcher (testbar mit Fake). Fehler → None."""
    try:
        data = fetcher(lat, lon)
        temperature = data["hourly"]["temperature_2m"][0]
        code = data["hourly"]["weather_code"][0]
    except Exception:
        return None
    return {
        "agent": "display",
        "title": "Wetter",
        "type": "weather",
        "data": {
            "temperature": _format_temperature(temperature),
            "condition": WEATHER_TEXT.get(code, "unbekannt"),
        },
        "updated_at": _now_iso(),
    }


def calendar_card(path: str) -> dict | None:
    """Kalender-Card aus einer lokalen JSON-Datei. Fehlt/leer → None."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        events = raw.get("events", [])
    except (OSError, json.JSONDecodeError):
        return None
    if not events:
        return None
    today = datetime.date.today().isoformat()
    lines = []
    for event in events:
        date = event.get("date", "")
        title = event.get("title", "")
        prefix = "heute" if date == today else date
        lines.append(f"{prefix}: {title}")
    return {
        "agent": "display",
        "title": "Kalender",
        "type": "calendar",
        "data": {"events": lines},
        "updated_at": _now_iso(),
    }
```

Step 4 — Run and verify pass
Step 5 — Commit: `git add src/max/display/providers.py tests/test_display_providers.py && git commit -m "max: display providers (clock, weather, calendar)"`

## Task 3: DisplayServer (server.py)

Files:
- Create: src/max/display/server.py
- Create: src/max/display/__main__.py
- Create: tests/test_display_server.py

Step 1 — Failing tests (tests/test_display_server.py):

```python
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
            line = request.readline().decode("utf-8")
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
```

Step 2 — Run and verify failure → FAIL (Modul fehlt)

Step 3 — Implement src/max/display/server.py:

```python
"""Display-Server: serviert die Mirror-Seite und streamt Card-Updates.

Endpunkte:
- GET /          → index.html (aus static/)
- GET /style.css → style.css
- GET /api/cards → JSON-Liste aller Cards (Routine + Agent-Cards)
- GET /events    → SSE-Stream: meldet neue/geänderte Agent-Cards

Der Server startet einen Hintergrund-Thread, der das Card-Verzeichnis
alle POLL_INTERVAL Sekunden pollt und bei Änderungen den Snapshot
aktualisiert. SSE-Clients erhalten die Änderungen als Events.
"""
import collections
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from max.display.cards import CardStore
from max.display.providers import DEFAULT_LAT, DEFAULT_LON, calendar_card, clock_card, open_meteo_fetcher, weather_card

# Intervall für das Polling des Card-Verzeichnisses
POLL_INTERVAL = 2.0

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class DisplayHandler(BaseHTTPRequestHandler):
    """Handler mit den Endpunkten. Snapshot/Events werden auf dem httpd-Objekt injiziert."""

    def log_message(self, fmt, *args):
        pass  # ruhig bleiben — keine Request-Logs

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html")
        elif self.path == "/style.css":
            self._serve_file(os.path.join(STATIC_DIR, "style.css"), "text/css")
        elif self.path == "/api/cards":
            self._serve_json(self.server.cards_snapshot())
        elif self.path == "/events":
            self._serve_sse()
        else:
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
        snap = json.dumps(self.server.cards_snapshot(), ensure_ascii=False)
        self.wfile.write(f"event: snapshot\ndata: {snap}\n\n".encode("utf-8"))
        self.flush()
        while True:
            try:
                card = self.server.wait_for_change(timeout=10)
            except TimeoutError:
                self.wfile.write(b": keepalive\n\n")
                self.flush()
                continue
            payload = json.dumps(card, ensure_ascii=False)
            self.wfile.write(f"event: card\ndata: {payload}\n\n".encode("utf-8"))
            self.flush()


class DisplayServer:
    """Kapselt HTTP-Server, CardStore und Routine-Cards."""

    def __init__(self, card_dir: str, calendar_path: str | None = None,
                 fetcher=None, lat: float | None = None, lon: float | None = None,
                 weather_ttl: float = 3600.0):
        self.card_dir = card_dir
        self.store = CardStore(card_dir)
        self.calendar_path = calendar_path
        self.fetcher = fetcher or open_meteo_fetcher
        self.lat = lat or DEFAULT_LAT
        self.lon = lon or DEFAULT_LON
        self.weather_ttl = weather_ttl
        self._snapshot: list[dict] = []
        self._weather_cache: dict | None = None
        self._weather_expires = 0.0
        self._event_queue = collections.deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._refresh_snapshot()

    def _refresh_snapshot(self):
        """Baut den aktuellen Card-Snapshot (Routine-Cards + Agent-Cards)."""
        with self._lock:
            routine = [clock_card()]
            if self._weather_cache is not None and time.time() < self._weather_expires:
                weather = self._weather_cache
            else:
                weather = weather_card(self.fetcher, self.lat, self.lon)
                self._weather_cache = weather
                self._weather_expires = time.time() + self.weather_ttl
            if weather:
                routine.append(weather)
            if self.calendar_path:
                cal = calendar_card(self.calendar_path)
                if cal:
                    routine.append(cal)
            agent = self.store.load_all()
            self._snapshot = routine + agent

    def cards_snapshot(self) -> list[dict]:
        return list(self._snapshot)

    def poll_store(self) -> list[dict]:
        """Polt das Card-Verzeichnis; bei Änderungen Snapshot aktualisieren + Events queuen."""
        changed = self.store.poll()
        if changed:
            self._refresh_snapshot()
            with self._lock:
                for card in changed:
                    self._event_queue.append(card)
        return changed

    def wait_for_change(self, timeout: float = 10.0):
        """Blockt, bis eine geänderte Card im Queue liegt (sonst Timeout)."""
        with self._lock:
            end = time.time() + timeout
            while True:
                if self._event_queue:
                    return self._event_queue.popleft()
                if time.time() >= end:
                    raise TimeoutError
                time.sleep(0.2)

    def _poll_loop(self):
        while not self._stop.is_set():
            self.poll_store()
            time.sleep(POLL_INTERVAL)

    def _bind(self, host, port):
        httpd = ThreadingHTTPServer((host, port), DisplayHandler)
        httpd.cards_snapshot = self.cards_snapshot
        httpd.wait_for_change = self.wait_for_change
        threading.Thread(target=self._poll_loop, daemon=True).start()
        return httpd

    def serve_forever(self, host: str = "127.0.0.1", port: int = 8080):
        httpd = self._bind(host, port)
        httpd.serve_forever()

    def start_in_thread(self, host: str = "127.0.0.1", port: int = 8080):
        """Startet den Server in einem Daemon-Thread. Liefert das httpd-Objekt."""
        httpd = self._bind(host, port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd

    def stop(self):
        self._stop.set()
```

Step 4 — Implement src/max/display/__main__.py:

```python
"""Entry-Point: python -m max.display

Startet den Display-Server auf localhost (Port via MAX_DISPLAY_PORT, Default 8080).
"""
import os

from max.display.server import DisplayServer


def main():
    # display/__main__.py liegt 3 Ebenen tief → 4× dirname bis Repo-Root
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    card_dir = os.path.join(root, "data", "display", "cards")
    calendar_path = os.path.join(root, "config", "calendar.json")
    port = int(os.environ.get("MAX_DISPLAY_PORT", "8080"))
    DisplayServer(card_dir, calendar_path=calendar_path).serve_forever(port=port)


if __name__ == "__main__":
    main()
```

Step 5 — Run and verify pass:
`cd /home/user/max && uv run pytest tests/test_display_server.py -v` → PASS
Step 6 — Commit: `git add src/max/display/server.py src/max/display/__main__.py tests/test_display_server.py && git commit -m "max: display server with sse"`

## Task 4: Frontend (static/index.html + style.css)

Files:
- Create: src/max/display/static/index.html
- Create: src/max/display/static/style.css
- Create: tests/test_display_frontend.py

Step 1 — Failing test (tests/test_display_frontend.py):

```python
import os


def test_frontend_files():
    # tests/ liegt nur 1 Ebene unter dem Repo-Root → 2× dirname
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static = os.path.join(root, "src", "max", "display", "static")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert "EventSource" in html
    assert "/api/cards" in html
    assert "style.css" in html
    assert os.path.exists(os.path.join(static, "style.css"))
```

Step 2 — Run and verify failure → FAIL (Dateien fehlen)

Step 3 — Implement src/max/display/static/index.html:

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Max — Smart Mirror</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <h1>Max</h1>
  </header>
  <main id="cards"></main>
  <script>
    // Cards rendern: pro Typ ein eigenes Layout
    function renderCard(card) {
      var el = document.createElement("section");
      el.className = "card " + card.type;
      var h2 = document.createElement("h2");
      h2.textContent = card.title;
      el.appendChild(h2);
      var body = document.createElement("div");
      body.className = "body";
      var data = card.data || {};
      if (card.type === "calendar" && data.events) {
        data.events.forEach(function (line) {
          var row = document.createElement("div");
          row.textContent = line;
          body.appendChild(row);
        });
      } else if (card.type === "clock") {
        body.textContent = data.time;
      } else if (card.type === "weather") {
        body.textContent = data.temperature + " — " + data.condition;
      } else {
        for (var key in data) {
          var row = document.createElement("div");
          row.textContent = key + ": " + data[key];
          body.appendChild(row);
        }
      }
      el.appendChild(body);
      return el;
    }

    function renderAll(cards) {
      var container = document.getElementById("cards");
      container.innerHTML = "";
      cards.forEach(function (card) {
        container.appendChild(renderCard(card));
      });
    }

    function loadCards() {
      fetch("/api/cards").then(function (r) {
        return r.json();
      }).then(renderAll);
    }

    loadCards();
    setInterval(loadCards, 5000);

    // Live-Update: bei jeder geänderten Agent-Card neu laden
    var source = new EventSource("/events");
    source.addEventListener("card", function () {
      loadCards();
    });
  </script>
</body>
</html>
```

Step 4 — Implement src/max/display/static/style.css:

```css
/* Dark Theme für den Smart Mirror */
body {
  margin: 0;
  background: #0b0f14;
  color: #e6edf3;
  font-family: "Segoe UI", system-ui, sans-serif;
}

header {
  padding: 24px 32px 8px;
}

h1 {
  margin: 0;
  font-size: 28px;
  letter-spacing: 2px;
}

#cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  padding: 24px 32px;
}

.card {
  background: #161b22;
  border-radius: 12px;
  padding: 16px;
  min-height: 120px;
}

.card h2 {
  margin: 0 0 12px;
  font-size: 18px;
}

.card.clock {
  font-size: 48px;
}

.card.weather .body {
  font-size: 24px;
}

.card.meal .body div {
  margin-bottom: 4px;
}
```

Step 5 — Run and verify pass:
`cd /home/user/max && uv run pytest tests/test_display_frontend.py -v` → PASS
Step 6 — Commit: `git add src/max/display/static tests/test_display_frontend.py && git commit -m "max: display frontend (mirror page)"`

## Task 5: Agent-Integration (card_path durch die Kette)

Files:
- Modify: src/max/agents/runner.py
- Modify: src/max/agents/nutrition.py
- Modify: config/opencode/ernaehrungsplaner.prompt.md
- Create: config/calendar.json
- Create: tests/test_agent_cards.py

Step 1 — Failing tests (tests/test_agent_cards.py):

```python
from max.agents.nutrition import nutrition_profile
from max.agents.runner import OpencodeRunner, build_task_message


def test_build_task_message_with_card_path():
    msg = build_task_message("Plan für heute", "Memory...", card_path="data/display/cards/ernaehrungsplaner.json")
    assert "data/display/cards/ernaehrungsplaner.json" in msg
    assert "updated_at" in msg


def test_build_task_message_without_card_path():
    msg = build_task_message("Plan für heute", "Memory...")
    assert "Display-Card" not in msg


def test_nutrition_profile_has_card_path():
    profile = nutrition_profile()
    assert profile["card_path"] == "data/display/cards/ernaehrungsplaner.json"


def test_opencode_runner_resolves_card_path():
    runner = OpencodeRunner(opencode_dir="/home/user/max/config/opencode")
    assert runner._resolve_path("data/display/cards/x.json") == "/home/user/max/data/display/cards/x.json"
```

Step 2 — Run and verify failure → FAIL (card_path fehlt)

Step 3 — Modify src/max/agents/runner.py:

(a) build_task_message mit optionalem card_path:

```python
def build_task_message(task: str, memory_context: str, card_path: str | None = None) -> str:
    """Setzt den Task-Prompt aus Nutzeranfrage und Memory-Kontext zusammen.

    Enthält die Anweisung zur strukturierten Eskalation, damit der Router
    das HITL-Gate deterministisch auslösen kann. Mit card_path erhält der
    Agent zusätzlich die Anweisung, eine Display-Card zu schreiben.
    """
    message = (
        f"Aufgabe: {task}\n\n"
        f"Dein Memory-Kontext:\n{memory_context}\n\n"
        "Wenn die Aufgabe lokal nicht lösbar ist (z. B. medizinische, juristische "
        "oder sehr komplexe Fragen), antworte AUSSCHLIESSLICH mit:\n"
        f"{ESCALATION_MARKER} <kurze Begründung>"
    )
    if card_path:
        message += (
            "\n\n## Display-Card\n"
            f"Schreibe dein Ergebnis als Card-JSON-Datei in den Pfad: {card_path}\n"
            "Schema: {\"agent\": \"<dein Name>\", \"title\": \"<Titel>\", "
            "\"type\": \"<typ>\", \"data\": {<key: value>}, \"updated_at\": \"<ISO-Zeit>\"}\n"
            "Typen: meal, weather, calendar, clock, generic."
        )
    return message
```

(b) OpencodeRunner: neuer _resolve_path (auch für memory_dir genutzt):

```python
    def _resolve_path(self, path: str) -> str:
        """Auflösung eines relativen Pfads gegen den Repo-Root (Eltern von config/opencode)."""
        if os.path.isabs(path):
            return path
        if self.opencode_dir:
            repo_root = os.path.dirname(os.path.dirname(self.opencode_dir))
            return os.path.normpath(os.path.join(repo_root, path))
        return path

    def _resolve_memory_dir(self, agent_profile: dict) -> str:
        """Auflösung des Memory-Verzeichnisses (relativ → Repo-Root)."""
        return self._resolve_path(agent_profile["memory_dir"])
```

(c) OpencodeRunner.run: card_path auflösen und durchreichen:

```python
    def run(self, agent_profile: dict, task: str) -> AgentResult:
        """Führt den Agent aus und parst die Ausgabe (Antwort/Eskalation)."""
        memory = FileMemory(self._resolve_memory_dir(agent_profile))
        card_path = agent_profile.get("card_path")
        if card_path:
            card_path = self._resolve_path(card_path)
        prompt = build_task_message(task, memory.get_context(), card_path)
        command = self.build_command(agent_profile) + [prompt]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError:
            # opencode nicht gefunden → sicher eskalieren statt abstürzen
            return AgentResult(answer="", escalated=True, escalation_reason="opencode nicht gefunden")
        except subprocess.TimeoutExpired:
            return AgentResult(answer="", escalated=True, escalation_reason="Timeout")
        if proc.returncode != 0:
            raise RuntimeError(f"opencode exit_code={proc.returncode}: {proc.stderr or proc.stdout}")
        output = (proc.stdout or "").strip()
        if not output and proc.stderr:
            output = proc.stderr.strip()
        return parse_agent_output(output)
```

Step 4 — Modify src/max/agents/nutrition.py: im return-Dict von nutrition_profile() den Eintrag ergänzen:

```python
        "memory_dir": "data/agents/ernaehrungsplaner",
        "card_path": "data/display/cards/ernaehrungsplaner.json",
```

Step 5 — Create config/calendar.json:

```json
{
  "events": [
    {"date": "2026-08-25", "title": "Beispiel: Zahnarzt"}
  ]
}
```

Step 6 — Modify config/opencode/ernaehrungsplaner.prompt.md — neue Sektion am Ende anhängen:

```markdown
## Display-Card (Smart Mirror)
Dein Ergebnis soll auf dem Smart Mirror angezeigt werden.
Schreibe nach dem Planen eine Card-JSON-Datei in den Card-Pfad aus der Aufgabe:
- Schema: {"agent": "ernaehrungsplaner", "title": "Heute: Ernährung", "type": "meal",
  "data": {"breakfast": "...", "lunch": "...", "dinner": "..."}, "updated_at": "<ISO-Zeit>"}
- Nur gültiges JSON, keine Kommentare.
```

Step 7 — Run and verify pass:
`cd /home/user/max && uv run pytest tests/test_agent_cards.py -v` → PASS
Step 8 — Commit:
`git add src/max/agents/runner.py src/max/agents/nutrition.py config/opencode/ernaehrungsplaner.prompt.md config/calendar.json tests/test_agent_cards.py && git commit -m "max: agent card_path integration"`

## Task 6: main.py — Flag --serve-display

Files:
- Modify: src/max/main.py

Step 1 — Modify src/max/main.py:

(a) In main() als ersten Schritte argparse ergänzen:

```python
def main():
    import argparse
    import sounddevice as sd  # noqa: F841 — sicher, dass der Import am Start funktioniert

    parser = argparse.ArgumentParser(description="Max — lokaler Sprachassistent")
    parser.add_argument("--serve-display", action="store_true",
                        help="startet zusätzlich den Display-Server (localhost)")
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

(b) Nach der Graph-Konstruktion und vor der while-Schleife den Display-Server starten:

```python
    if args.serve_display:
        from max.display.server import DisplayServer
        card_dir = os.path.join(root, "data", "display", "cards")
        DisplayServer(
            card_dir,
            calendar_path=os.path.join(root, "config", "calendar.json"),
        ).start_in_thread(port=int(os.environ.get("MAX_DISPLAY_PORT", "8080")))
```

Step 2 — Verify: `uv run python -c "import max.main"` kompiliert sauber (Syntax-Check)
Step 3 — Commit: `git add src/max/main.py && git commit -m "max: serve-display flag"`

## Task 7: E2E-Test (Card-Write → API → SSE)

Files:
- Create: tests/test_display_e2e.py

Step 1 — Implement tests/test_display_e2e.py:

```python
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
```

Step 2 — Run and verify pass:
`cd /home/user/max && uv run pytest tests/test_display_e2e.py -v` → PASS
Step 3 — Commit: `git add tests/test_display_e2e.py && git commit -m "max: display e2e test"`

## Task 8: Finale Verifikation

Step 1 — Vollständiger Testlauf:
`cd /home/user/max && uv run pytest -v` → alle Tests grün (vorher 51 + neue Display-Tests)

Step 2 — Syntax-Check aller neuen Module:
`cd /home/user/max && uv run python -m py_compile src/max/display/cards.py src/max/display/providers.py src/max/display/server.py src/max/display/__main__.py src/max/main.py`

Step 3 — Verifikation ohne Netzwerk: Testen mit Fakes (bereits erfüllt durch injectable fetcher)

Step 4 — Finaler Commit, falls noch etwas offen ist
`git status` → working tree clean

## Verification

- [ ] uv run pytest -v → alle Tests grün
- [ ] py_compile auf allen neuen Modulen
- [ ] git status clean
- [ ] Card-Flow: Agent schreibt JSON → Server pollt → /api/cards zeigt Card → SSE Event → Frontend rendert
- [ ] Wetter offline-safe (kein Crash ohne Netzwerk)
