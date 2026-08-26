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
