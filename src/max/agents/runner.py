"""Agent-Runner: führt Fach-Agenten über pluggable Backends aus.

Der Runner nimmt das Agent-Profil (dict), liest den Memory-Kontext
(FileMemory) und baut daraus den Task-Prompt. Backends:
- OpencodeRunner: ruft `opencode run` nicht-interaktiv auf. Der opencode-Agent
  (inkl. Mealie-MCP-Server) ist in config/opencode/opencode.json definiert;
  der Runner überreicht den zusammengesetzten Prompt als Message.
- MockAgentRunner: Offline-Stub für Tests ohne echten opencode-Launch.

Eskalation: Ein Agent, der die Aufgabe lokal nicht lösen kann, antwortet
mit "[ESCALATE] <grund>". parse_agent_output() macht daraus ein strukturiertes
AgentResult, mit dem der Router das HITL-Gate steuert.
"""
import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from max.agents.memory import FileMemory

# Marker, mit dem ein Agent signalisiert, dass Server 2 gebraucht wird
ESCALATION_MARKER = "[ESCALATE]"


@dataclass
class AgentResult:
    """Ergebnis eines Agent-Laufs: Antwort und/oder Eskalation."""
    answer: str
    escalated: bool = False
    escalation_reason: str | None = None


def parse_agent_output(raw: str) -> AgentResult:
    """Trennt die Agent-Ausgabe in Antwort und Eskalation.

    Ohne Marker: normale Antwort.
    Mit Marker: Eskalation; der Text vor dem Marker wird die Antwort
    (darf leer sein), der Text danach ist der Grund.
    """
    raw = (raw or "").strip()
    idx = raw.find(ESCALATION_MARKER)
    if idx == -1:
        return AgentResult(answer=raw)
    reason = raw[idx + len(ESCALATION_MARKER):].strip()
    answer = raw[:idx].strip()
    return AgentResult(answer=answer, escalated=True, escalation_reason=reason)


def extract_answer(events: list) -> str:
    """Concateniert die Text-Antworten aus den SSE-Events (data.text von text.ended)."""
    texts = []
    for ev in events:
        if ev.get("type") == "session.next.text.ended":
            props = ev.get("data") or ev.get("properties") or ev.get("payload") or {}
            texts.append(props.get("text", ""))
    return "".join(texts)


def build_task_message(task: str, memory_context: str, person_context: str = "",
                       card_path: str | None = None, person_path: str | None = None) -> str:
    """Setzt den Task-Prompt aus Nutzeranfrage, Memory- und Personen-Kontext zusammen.

    Enthält die Anweisung zur strukturierten Eskalation, damit der Router
    das HITL-Gate deterministisch auslösen kann. Mit card_path erhält der
    Agent zusätzlich die Anweisung, eine Display-Card zu schreiben. Mit
    person_path erhält er die Anweisung, neue dauerhafte Fakten ins
    gemeinsame Personen-Profil eintragen.
    """
    message = (
        f"Aufgabe: {task}\n\n"
        f"Dein Memory-Kontext:\n{memory_context}\n"
    )
    if person_context:
        message += f"\nDein Personen-Profil:\n{person_context}\n"
    message += (
        "\nWenn die Aufgabe lokal nicht lösbar ist (z. B. medizinische, juristische "
        "oder sehr komplexe Fragen), antworte AUSSCHLIESSLICH mit:\n"
        f"{ESCALATION_MARKER} <kurze Begründung>"
    )
    if person_path:
        message += (
            f"\n\n## Personen-Profil\n"
            f"Neue dauerhafte Fakten über die Person (Allergien, Ziele, Vorlieben, "
            f"Beschränkungen) trägst du als YAML in die Datei {person_path} ein. "
            f"Bestehende Einträge ergänzen, nicht überschreiben."
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


class AgentRunner:
    """Abstraktes Backend für den Lauf von Fach-Agenten."""

    def run(self, agent_profile: dict, task: str) -> AgentResult:
        """Führt die Aufgabe aus und liefert Antwort (ggf. Eskalation)."""
        raise NotImplementedError


class MockAgentRunner(AgentRunner):
    """Offline-Mock für Tests: feste Antwort, optional Eskalation."""

    def __init__(self, answer: str = "Mock-Antwort", escalated: bool = False, reason: str = "zu komplex"):
        self._answer = answer
        self._escalated = escalated
        self._reason = reason

    def run(self, agent_profile: dict, task: str) -> AgentResult:
        if self._escalated:
            return AgentResult(answer="", escalated=True, escalation_reason=self._reason)
        return AgentResult(answer=f"{self._answer} zu: {task}")


class OpencodeRunner(AgentRunner):
    """Führt einen opencode-Agenten über die opencode-Server-API (HTTP + SSE) aus.

    Die opencode-CLI (`opencode run`) gibt in Nicht-TTY-Modus keine Ausgabe,
    daher nutzt der Runner `opencode serve`: Bei Bedarf wird der Server mit
    cwd=opencode_dir gestartet (damit die Projekt-Agenten geladen werden),
    eine Session wird angelegt, der Agent gesetzt, der SSE-Eventstrom geöffnet
    und der Prompt gesendet. Die Text-Antworten werden aus den
    `session.next.text.ended`-Events (data.text) zusammengebaut.
    Relativ memory_dir-Pfade werden gegen den Repo-Root (Eltern von
    config/opencode) aufgelöst, damit die Memory-Dateien in data/agents/<name>/ landen.
    """

    def __init__(self, opencode_bin: str = "opencode", opencode_dir: str | None = None,
                 port: int = 4096, base_url: str = None, timeout: float = 120.0, person_memory=None):
        self.opencode_bin = opencode_bin
        self.opencode_dir = opencode_dir
        self.port = port
        self.base_url = base_url or f"http://127.0.0.1:{port}"
        self.timeout = timeout
        self.person_memory = person_memory
        self._server_proc = None

    def _resolve_path(self, path: str) -> str:
        """Auflösung eines relativen Pfads gegen den Repo-Root (Eltern von config/opencode)."""
        if not path:
            return path
        if os.path.isabs(path):
            return path
        if self.opencode_dir:
            repo_root = os.path.dirname(os.path.dirname(self.opencode_dir))
            return os.path.normpath(os.path.join(repo_root, path))
        return path

    def _resolve_memory_dir(self, agent_profile: dict) -> str:
        """Auflösung des Memory-Verzeichnisses (relativ → Repo-Root)."""
        return self._resolve_path(agent_profile["memory_dir"])

    # --- Server-Verwaltung ---
    def _server_ready(self) -> bool:
        """Echte opencode-Server oder Test-Server auf base_url erreichbar?"""
        try:
            urllib.request.urlopen(self.base_url + "/agent", timeout=3)
            return True
        except Exception:
            return False

    def _ensure_server(self) -> None:
        """Stellt sicher, dass ein opencode-Server auf base_url erreichbar ist."""
        if self._server_ready():
            return
        # uvx (Mealie-MCP) liegt typischerweise in ~/.local/bin, das nicht immer im PATH.
        env = os.environ.copy()
        extra_bin = os.path.expanduser("~/.local/bin")
        if os.path.isdir(extra_bin) and extra_bin not in env.get("PATH", ""):
            env["PATH"] = extra_bin + os.pathsep + env.get("PATH", "")
        proc = subprocess.Popen(
            [self.opencode_bin, "serve", "--port", str(self.port)],
            cwd=self.opencode_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._server_proc = proc
        deadline = time.time() + self.timeout
        while time.time() < deadline and not self._server_ready():
            time.sleep(0.5)

    # --- HTTP-Helfer ---
    def _post(self, path: str, body) -> bytes:
        data = json.dumps(body).encode() if body is not None else b""
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(req, timeout=self.timeout).read()

    def run(self, agent_profile: dict, task: str) -> AgentResult:
        """Führt den Agent aus und parst die Ausgabe (Antwort/Eskalation)."""
        memory = FileMemory(self._resolve_memory_dir(agent_profile))
        person_context = self.person_memory.get_context() if self.person_memory is not None else ""
        person_path = agent_profile.get("person_path")
        if person_path:
            person_path = self._resolve_path(person_path)
        card_path = agent_profile.get("card_path")
        if card_path:
            card_path = self._resolve_path(card_path)
        prompt = build_task_message(task, memory.get_context(), person_context, card_path, person_path)

        self._ensure_server()

        # Session anlegen (POST /session)
        sess_raw = self._post("/session?directory=" + urllib.parse.quote(self.opencode_dir), None)
        sid = json.loads(sess_raw)["id"]

        # Agent setzen (POST /api/session/{id}/agent)
        self._post(f"/api/session/{sid}/agent", {"agent": agent_profile["name"]})

        # SSE-Eventstrom öffnen (muss vor dem Prompt sein)
        events: list = []
        done = threading.Event()

        def stream():
            try:
                req = urllib.request.Request(self.base_url + f"/api/session/{sid}/event")
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                for raw in resp:
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        ev = json.loads(payload)
                        events.append(ev)
                        if ev.get("type") == "session.next.step.ended":
                            done.set()
                            break
                    except Exception:
                        pass
                done.set()
            except Exception:
                done.set()

        t = threading.Thread(target=stream, daemon=True)
        t.start()
        time.sleep(0.3)  # SSE-Verbindung aufbauen lassen

        # Prompt senden
        self._post(f"/api/session/{sid}/prompt", {"prompt": {"text": prompt}})

        # Auf Fertigstellung warten
        done.wait(self.timeout)
        t.join(5)

        return parse_agent_output(extract_answer(events))
