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
    bind = os.environ.get("MAX_REMOTE_BIND", "0.0.0.0")
    Server2Service(make_backend_from_env(), host=bind, port=port).serve_forever()


if __name__ == "__main__":
    main()
