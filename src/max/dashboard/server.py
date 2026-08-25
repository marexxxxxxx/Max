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
