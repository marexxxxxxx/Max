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
import os
import subprocess
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
    """Ruft `opencode run` nicht-interaktiv auf.

    Der opencode-Agent (inkl. Mealie-MCP) ist in config/opencode/opencode.json
    definiert. Relativ memory_dir-Pfade werden gegen den Repo-Root (Elterner
    von config/opencode) aufgelöst, damit die Memory-Dateien in
    data/agents/<name>/ landen.
    """

    def __init__(self, opencode_bin: str = "opencode", opencode_dir: str | None = None,
                 timeout: float = 120.0, person_memory=None):
        self.opencode_bin = opencode_bin
        self.opencode_dir = opencode_dir
        self.timeout = timeout
        self.person_memory = person_memory

    def build_command(self, agent_profile: dict) -> list[str]:
        """Baut die Kommandozeile für einen Agent-Lauf."""
        command = [self.opencode_bin, "run"]
        if self.opencode_dir:
            command += ["--dir", self.opencode_dir]
        command += ["--agent", agent_profile["name"]]
        return command

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
