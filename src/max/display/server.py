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
        self.wfile.flush()
        while True:
            try:
                card = self.server.wait_for_change(timeout=10)
            except TimeoutError:
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                continue
            payload = json.dumps(card, ensure_ascii=False)
            self.wfile.write(f"event: card\ndata: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()


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
        end = time.time() + timeout
        while True:
            with self._lock:
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
