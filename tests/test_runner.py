import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from max.agents.person import PersonMemory
from max.agents.runner import (
    MockAgentRunner,
    OpencodeRunner,
    build_task_message,
    extract_answer,
    parse_agent_output,
)


def test_parse_plain_answer():
    result = parse_agent_output("Hier ist dein Ernährungsplan.")
    assert result.answer == "Hier ist dein Ernährungsplan."
    assert result.escalated is False


def test_parse_escalation():
    result = parse_agent_output("Ich brauche den großen Rechner. [ESCALATE] medizinische Frage")
    assert result.escalated is True
    assert result.escalation_reason == "medizinische Frage"
    assert result.answer == "Ich brauche den großen Rechner."


def test_parse_escalation_only():
    result = parse_agent_output("[ESCALATE] zu komplex")
    assert result.escalated is True
    assert result.escalation_reason == "zu komplex"
    assert result.answer == ""


def test_build_task_message():
    msg = build_task_message("Plane eine Woche", "Profil: sport: Krafttraining")
    assert "Plane eine Woche" in msg
    assert "Profil: sport: Krafttraining" in msg
    assert "[ESCALATE]" in msg


def test_build_task_message_with_person():
    msg = build_task_message(
        "Plane eine Woche",
        "Profil: sport: Krafttraining",
        person_context="Personen-Profil:\n  allergien: ['Milch']",
        person_path="/data/memory/person.yaml",
    )
    assert "Personen-Profil:\n  allergien: ['Milch']" in msg
    assert "/data/memory/person.yaml" in msg


def test_extract_answer():
    events = [
        {"type": "session.next.text.started", "data": {}},
        {"type": "session.next.text.ended", "data": {"text": "Hallo "}},
        {"type": "session.next.text.ended", "data": {"text": "Welt"}},
        {"type": "session.next.step.ended", "data": {}},
    ]
    assert extract_answer(events) == "Hallo Welt"


def test_mock_runner_plain():
    runner = MockAgentRunner()
    result = runner.run({"name": "x"}, "Aufgabe")
    assert result.escalated is False
    assert "Aufgabe" in result.answer


def test_mock_runner_escalation():
    runner = MockAgentRunner(escalated=True, reason="nur mit Server 2")
    result = runner.run({"name": "x"}, "Aufgabe")
    assert result.escalated is True
    assert result.escalation_reason == "nur mit Server 2"


def test_relative_memory_dir_resolved_against_repo_root(tmp_path):
    # opencode_dir = <tmp>/config/opencode → Repo-Root = <tmp>/repo
    root = str(tmp_path / "repo")
    os.makedirs(os.path.join(root, "config", "opencode"), exist_ok=True)
    runner = OpencodeRunner(opencode_dir=os.path.join(root, "config", "opencode"))
    assert runner._resolve_memory_dir({"memory_dir": "data/agents/x"}) == \
        os.path.join(root, "data", "agents", "x")
    assert runner._resolve_path("data/memory/person.yaml") == \
        os.path.join(root, "data", "memory", "person.yaml")


def _start_fake_opencode_server(answer_text: str):
    """Startet einen Fake-Opencode-Server (HTTP + SSE) auf einem freien Port."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if "/event" in self.path:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                ev1 = {"type": "session.next.text.ended", "data": {"text": answer_text}}
                ev2 = {"type": "session.next.step.ended", "data": {}}
                for ev in (ev1, ev2):
                    self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode("utf-8"))
                    self.wfile.flush()
            elif "/agent" in self.path:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"[]")

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length:
                self.rfile.read(length)
            if self.path.startswith("/session"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"id": "ses_fake"}).encode("utf-8"))
            elif "/agent" in self.path:
                self.send_response(204)
                self.end_headers()
            elif "/prompt" in self.path:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def test_opencode_runner_fake_server_escalation(tmp_path):
    server, port = _start_fake_opencode_server("Antwort vorab [ESCALATE] Grund der Eskalation")
    runner = OpencodeRunner(
        opencode_dir=str(tmp_path),
        base_url=f"http://127.0.0.1:{port}",
        timeout=10.0,
    )
    result = runner.run(
        {"name": "ernaehrungsplaner", "memory_dir": str(tmp_path / "mem")},
        "Aufgabe",
    )
    assert result.escalated is True
    assert result.escalation_reason == "Grund der Eskalation"
    assert result.answer == "Antwort vorab"
    server.shutdown()


def test_opencode_runner_fake_server_plain(tmp_path):
    server, port = _start_fake_opencode_server("Alles klar")
    person = PersonMemory(str(tmp_path / "person.yaml"))
    person.write_category("allergien", ["Milch"])
    runner = OpencodeRunner(
        opencode_dir=str(tmp_path),
        base_url=f"http://127.0.0.1:{port}",
        timeout=10.0,
        person_memory=person,
    )
    result = runner.run(
        {"name": "x", "memory_dir": str(tmp_path / "mem"),
         "person_path": str(tmp_path / "person.yaml")},
        "Aufgabe",
    )
    assert result.answer == "Alles klar"
    assert result.escalated is False
    server.shutdown()
