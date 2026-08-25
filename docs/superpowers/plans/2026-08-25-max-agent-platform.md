# Max Agenten-Plattform (Subprojekt B) — Implementierungsplan

> **Für den Entwickler:** Jeder Task wird mit TDD ausgeführt: erst das fehlende Test schreiben und ausführen (muss fehlschlagen), dann implementieren, Test grüner machen, commit.

## Überblick

Max wird vom Demo-Skeleton zu einer **Plattform für mehrere Fach-Agenten**: generischer Agent-Runner mit pluggable Backends (opencode CLI), dateibasiertes Memory pro Agent, HITL-Gate (Sprachbestätigung vor Server 2) und der Ernährungsplaner als erstes Beispiel-Agent. Die Architektur ist von Grund auf multi-agent tauglich: ein neuer Agent = 1 YAML + 1 prompt.md + 1 opencode.json-Eintrag, ohne Architektur-Änderung.

## Globale Constraints

- Python 3.12, venv via uv: Tests mit `uv run pytest -q`
- Repo-Root: `/home/user/max`
- Tests laufen offline: keine Netzwerk-, GPU- oder Mikrofon-Zugriffe (MockAgentRunner + Fakes aus conftest.py)
- Nutzer-Strings und Code-Kommentare auf Deutsch, ausführlich kommentieren (globales Constraint)
- Schwere Imports (faster-whisper, pyannote, kokoro, sounddevice) bleiben lazy oder hinter Fakes
- Keine neuen Abhängigkeiten (yaml, langgraph sind schon da)
- opencode CLI ist auf der Maschine verfügbar (`opencode run --agent <name>`)
- Mealie-Env (`MEALIE_BASE_URL`, `MEALIE_API_KEY`) bleibt maschinenseitig, NICHT im Repo

## Dateien

Neu:
- `src/max/agents/memory.py` — AgentMemory-Interface + FileMemory
- `src/max/agents/runner.py` — AgentResult, parse_agent_output, AgentRunner, MockAgentRunner, OpencodeRunner
- `src/max/agents/nutrition.py` — Ernährungsplaner-Profil (Defaults)
- `src/max/router/hitl.py` — HITL-Frage + is_confirmation
- `config/agents/ernaehrungsplaner.yaml`
- `config/opencode/opencode.json` — opencode-Agent + Mealie-MCP
- `config/opencode/ernaehrungsplaner.prompt.md` — System-Prompt
- `tests/test_memory.py`, `tests/test_runner.py`, `tests/test_hitl.py`, `tests/test_nutrition.py`

Geändert:
- `src/max/router/graph.py` — neue State-Maschine (HITL + Runner)
- `src/max/main.py` — HITL-Loop + Runner-Wiring
- `tests/test_graph.py`, `tests/test_e2e.py` — neue Signatur
- `config/agents/demo.yaml` — wird entfernt (ersetzt durch Ernährungsplaner)
- `.gitignore` — `data/` ignorieren, falls noch nicht vorhanden

## Interfaces

- `FileMemory(agent_dir)` → `get_context()`, `read_profile()`, `write_profile(key, value)`, `append_note(text)`
- `AgentResult(answer, escalated=False, escalation_reason=None)` (dataclass)
- `parse_agent_output(raw) -> AgentResult`
- `build_task_message(task, memory_context) -> str`
- `MockAgentRunner(answer="Mock-Antwort", escalated=False, reason="zu komplex")`
- `OpencodeRunner(opencode_bin="opencode", opencode_dir=None, timeout=120.0)` mit `build_command(profile)` und `run(profile, task)`
- `HITL_QUESTION`, `is_confirmation(text) -> bool`
- `build_graph(transcriber, diarizer, registry, classifier, profiles, runner, server2)` — `profiles` ist eine **Liste** von Agent-Profilen (dicts)
- `nutrition_profile() -> dict`
- Neue State-Keys: `query`, `awaiting_confirmation`, `confirmation`; `route` wird `"local"` oder `"hitl"`

## Task 1: Memory (FileMemory)

**Files:** `src/max/agents/memory.py` (neu), `tests/test_memory.py` (neu)

**Step 1: Failing test schreiben** — `tests/test_memory.py`:

```python
from max.agents.memory import FileMemory


def test_empty_context(tmp_path):
    mem = FileMemory(str(tmp_path))
    assert mem.read_profile() == {}
    assert mem.get_context() == "(noch keine Erinnerungen)"


def test_profile_roundtrip(tmp_path):
    mem = FileMemory(str(tmp_path))
    mem.write_profile("allergien", "Erdnüsse")
    assert mem.read_profile() == {"allergien": "Erdnüsse"}


def test_append_note(tmp_path):
    mem = FileMemory(str(tmp_path))
    mem.append_note("Liebt Zitronen")
    mem.append_note("Vermeidet Zucker")
    text = (tmp_path / "memory.md").read_text(encoding="utf-8")
    assert "Liebt Zitronen" in text
    assert "Vermeidet Zucker" in text


def test_context_includes_profile_and_notes(tmp_path):
    mem = FileMemory(str(tmp_path))
    mem.write_profile("sport", "Krafttraining")
    mem.append_note("Ziel: 80g Protein")
    context = mem.get_context()
    assert "sport: Krafttraining" in context
    assert "Ziel: 80g Protein" in context
```

**Step 2: Ausführen** — `uv run pytest tests/test_memory.py -q` → muss fehlschlagen (Modul nicht vorhanden).

**Step 3: Implementieren** — `src/max/agents/memory.py`:

```python
"""Dateibasiertes Agent-Memory (Subprojekt B).

Jeder Fach-Agent führt sein eigenes kleines Gedächtnis:
- profile.yaml: strukturierte Angaben über die Person (Allergien, Ziele, Vorlieben)
- memory.md: freie Notizen (Gesprächshistorie, Korrekturen)

Die Memory-Dateien werden VON den Agenten selbst mit ihren Dateitools
geschrieben. Der Runner liest sie nur und injiziert den Inhalt als Kontext
in den Task-Prompt. Ein Vector- oder DB-Backend kann später über das
AgentMemory-Interface nachgerüstet werden, ohne den Runner zu ändern.
"""
import os

import yaml


class AgentMemory:
    """Abstraktes Interface für Agent-Memory.

    Die Methoden beschreiben die Minimal-Vertragsfläche, die der Runner
    braucht, um Kontext für den Task-Prompt zu sammeln.
    """

    def get_context(self) -> str:
        """Kompakter Kontext-Text für den Task-Prompt."""
        raise NotImplementedError

    def read_profile(self) -> dict:
        """Strukturiertes Profil (dict) zurückgeben."""
        raise NotImplementedError

    def write_profile(self, key: str, value) -> None:
        """Einen Wert ins Profil schreiben."""
        raise NotImplementedError

    def append_note(self, text: str) -> None:
        """Eine Notiz an memory.md anhängen."""
        raise NotImplementedError


class FileMemory(AgentMemory):
    """Datei-Memory: profile.yaml + memory.md im Agent-Verzeichnis."""

    def __init__(self, agent_dir: str):
        self.agent_dir = agent_dir
        self.profile_path = os.path.join(agent_dir, "profile.yaml")
        self.note_path = os.path.join(agent_dir, "memory.md")

    def read_profile(self) -> dict:
        """Liest profile.yaml; existiert die Datei nicht, leeres dict."""
        if not os.path.exists(self.profile_path):
            return {}
        with open(self.profile_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def write_profile(self, key: str, value) -> None:
        """Schreibt einen Wert in profile.yaml (idempotent, übergibt alte Werte)."""
        profile = self.read_profile()
        profile[key] = value
        os.makedirs(self.agent_dir, exist_ok=True)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(profile, f, allow_unicode=True, sort_keys=False)

    def append_note(self, text: str) -> None:
        """Hängt eine Zeile an memory.md an (Datei wird bei Bedarf angelegt)."""
        os.makedirs(self.agent_dir, exist_ok=True)
        with open(self.note_path, "a", encoding="utf-8") as f:
            f.write(f"\n{text}\n")

    def get_context(self) -> str:
        """Stellt Profil + Notizen als kompakten Kontext-Text zusammen."""
        profile = self.read_profile()
        lines = []
        if profile:
            lines.append("Profil:")
            for key, value in profile.items():
                lines.append(f"  {key}: {value}")
        if os.path.exists(self.note_path):
            with open(self.note_path, encoding="utf-8") as f:
                notes = f.read().strip()
            if notes:
                lines.append("Notizen:")
                lines.append(notes)
        if not lines:
            return "(noch keine Erinnerungen)"
        return "\n".join(lines)
```

**Step 4: Ausführen** — `uv run pytest tests/test_memory.py -q` → 4 passed.

**Step 5: Commit** — `git add -A && git commit -m "max: agent memory (FileMemory)"`

## Task 2: Runner (AgentRunner + Backends)

**Files:** `src/max/agents/runner.py` (neu), `tests/test_runner.py` (neu)

**Step 1: Failing test schreiben** — `tests/test_runner.py`:

```python
import os

from max.agents.runner import (
    MockAgentRunner,
    OpencodeRunner,
    build_task_message,
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


def test_opencode_runner_fake_bin(tmp_path):
    # Kleiner Stellvertreter für die opencode CLI: gibt eine Eskalation aus
    script = tmp_path / "fake-opencode"
    script.write_text(
        "#!/bin/sh\nprintf 'Antwort vorab [ESCALATE] Grund der Eskalation'\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o755)
    runner = OpencodeRunner(opencode_bin=str(script), opencode_dir=str(tmp_path), timeout=10.0)
    result = runner.run(
        {"name": "ernaehrungsplaner", "memory_dir": str(tmp_path / "mem")},
        "Aufgabe",
    )
    assert result.escalated is True
    assert result.escalation_reason == "Grund der Eskalation"
    assert result.answer == "Antwort vorab"


def test_opencode_runner_command():
    runner = OpencodeRunner(opencode_bin="opencode", opencode_dir="/tmp/x")
    cmd = runner.build_command({"name": "ernaehrungsplaner"})
    assert cmd == ["opencode", "run", "--dir", "/tmp/x", "--agent", "ernaehrungsplaner"]
```

**Step 2: Ausführen** — `uv run pytest tests/test_runner.py -q` → muss fehlschlagen (Modul nicht vorhanden).

**Step 3: Implementieren** — `src/max/agents/runner.py`:

```python
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


def build_task_message(task: str, memory_context: str) -> str:
    """Setzt den Task-Prompt aus Nutzeranfrage und Memory-Kontext zusammen.

    Enthält die Anweisung zur strukturierten Eskalation, damit der Router
    das HITL-Gate deterministisch auslösen kann.
    """
    return (
        f"Aufgabe: {task}\n\n"
        f"Dein Memory-Kontext:\n{memory_context}\n\n"
        "Wenn die Aufgabe lokal nicht lösbar ist (z. B. medizinische, juristische "
        "oder sehr komplexe Fragen), antworte AUSSCHLIESSLICH mit:\n"
        f"{ESCALATION_MARKER} <kurze Begründung>"
    )


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

    def __init__(self, opencode_bin: str = "opencode", opencode_dir: str | None = None, timeout: float = 120.0):
        self.opencode_bin = opencode_bin
        self.opencode_dir = opencode_dir
        self.timeout = timeout

    def build_command(self, agent_profile: dict) -> list[str]:
        """Baut die Kommandozeile für einen Agent-Lauf."""
        command = [self.opencode_bin, "run"]
        if self.opencode_dir:
            command += ["--dir", self.opencode_dir]
        command += ["--agent", agent_profile["name"]]
        return command

    def _resolve_memory_dir(self, agent_profile: dict) -> str:
        """Auflösung des Memory-Verzeichnisses (relativ → Repo-Root)."""
        memory_dir = agent_profile["memory_dir"]
        if os.path.isabs(memory_dir):
            return memory_dir
        if self.opencode_dir:
            repo_root = os.path.dirname(os.path.dirname(self.opencode_dir))
            return os.path.join(repo_root, memory_dir)
        return memory_dir

    def run(self, agent_profile: dict, task: str) -> AgentResult:
        """Führt den Agent aus und parst die Ausgabe (Antwort/Eskalation)."""
        memory = FileMemory(self._resolve_memory_dir(agent_profile))
        prompt = build_task_message(task, memory.get_context())
        command = self.build_command(agent_profile) + [prompt]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError:
            # opencode nicht gefunden → sicher eskalieren statt abstürzen
            return AgentResult(answer="", escalated=True, escalation_reason="opencode nicht gefunden")
        except subprocess.TimeoutExpired:
            return AgentResult(answer="", escalated=True, escalation_reason="Timeout")
        output = (proc.stdout or "").strip()
        if not output and proc.stderr:
            output = proc.stderr.strip()
        return parse_agent_output(output)
```

**Step 4: Ausführen** — `uv run pytest tests/test_runner.py -q` → 8 passed.

**Step 5: Commit** — `git add -A && git commit -m "max: agent runner (opencode + mock backend)"`

## Task 3: HITL-Gate-Helfer

**Files:** `src/max/router/hitl.py` (neu), `tests/test_hitl.py` (neu)

**Step 1: Failing test schreiben** — `tests/test_hitl.py`:

```python
from max.router.hitl import HITL_QUESTION, is_confirmation


def test_yes_variants():
    assert is_confirmation("Ja")
    assert is_confirmation("ja, bitte")
    assert is_confirmation("Yes")
    assert is_confirmation("Natürlich")


def test_no_variants():
    assert not is_confirmation("Nein")
    assert not is_confirmation("nein, lass ihn aus")
    assert not is_confirmation("")
    assert not is_confirmation(None)


def test_question_is_german():
    assert "Server 2" in HITL_QUESTION
```

**Step 2: Ausführen** — `uv run pytest tests/test_hitl.py -q` → muss fehlschlagen.

**Step 3: Implementieren** — `src/max/router/hitl.py`:

```python
"""Human-in-the-loop Gate: vor dem Umschalten auf Server 2 muss der
Nutzer per Sprache bestätigen.

Das Gate ist als Graph-Node integriert: nach „respond_remote" oder einer
Agent-Eskalation liefert der erste Turn die Frage (HITL_QUESTION).
Die Bestätigungsrunde kommt als zweiter Graph-Aufruf (state["confirmation"]);
der Node „confirm" entscheidet dann: ja → Server 2, nein → lokal bleiben.
"""

# Frage, die Max vor dem Server-2-Umschalten stellt
HITL_QUESTION = "Das braucht den großen Rechner (Server 2). Soll ich ihn einschalten?"

# Wörter, mit denen eine Bestätigung eindeutig beginnt
CONFIRMATION_WORDS = {"ja", "yes", "bitte", "klar", "natürlich", "selbstverständlich", "absolut"}


def is_confirmation(text: str) -> bool:
    """Liefert True, wenn die Äußerung mit einem eindeutigen Ja beginnt.

    Wir prüfen nur das erste Wort, damit „Nein, lass ihn aus" nicht
    versehentlich als Zustimmung gezählt wird.
    """
    words = (text or "").strip().lower().split()
    if not words:
        return False
    return words[0] in CONFIRMATION_WORDS
```

**Step 4: Ausführen** — `uv run pytest tests/test_hitl.py -q` → 3 passed.

**Step 5: Commit** — `git add -A && git commit -m "max: hitl gate helpers"`

## Task 4: Graph-Neubau (HITL + Runner)

**Files:** `src/max/router/graph.py` (Umschreiben), `tests/test_graph.py` (Umschreiben)

Neue Signatur: `build_graph(transcriber, diarizer, registry, classifier, profiles, runner, server2)`.
`profiles` ist eine **Liste** von Agent-Profil-Dicts (statt dict von DemoAgent-Objekten).
Neue State-Keys: `query`, `awaiting_confirmation`, `confirmation`; `route` wird `"local"` oder `"hitl"`.

**Step 1: Failing tests schreiben** — `tests/test_graph.py` komplett ersetzen:

```python
from max.agents.runner import MockAgentRunner
from max.remote.server2 import MockServer2
from max.router.graph import build_graph
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def _profiles():
    return [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}]


def _graph(classifier, runner=None):
    runner = runner if runner is not None else MockAgentRunner()
    return build_graph(
        FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
        classifier, _profiles(), runner, MockServer2(),
    )


def test_local_route():
    result = _graph(FakeClassifier(agent="ernaehrungsplaner")).invoke({"audio": b"xx"})
    assert result["route"] == "local"
    assert result["speaker"] == "Alex"
    assert result["answer"] == "Mock-Antwort zu: Testfrage"
    assert result["awaiting_confirmation"] is False


def test_remote_route_asks_confirmation():
    result = _graph(FakeClassifier(remote_needed=True)).invoke({"audio": b"xx"})
    assert result["route"] == "hitl"
    assert result["awaiting_confirmation"] is True
    assert result["answer"].startswith("Das braucht den großen Rechner")
    assert result["query"] == "Testfrage"


def test_low_confidence_goes_hitl():
    result = _graph(FakeClassifier(confidence=0.2, agent="ernaehrungsplaner")).invoke({"audio": b"xx"})
    assert result["route"] == "hitl"
    assert result["awaiting_confirmation"] is True


def test_unknown_agent_goes_hitl():
    result = _graph(FakeClassifier(agent="unbekannt")).invoke({"audio": b"xx"})
    assert result["route"] == "hitl"


def test_classifier_failure_goes_hitl():
    class Broken:
        def classify(self, text, agents):
            raise RuntimeError("ollama down")
    result = _graph(Broken()).invoke({"audio": b"xx"})
    assert result["route"] == "hitl"


def test_agent_escalation_goes_hitl():
    runner = MockAgentRunner(escalated=True, reason="medizinische Frage")
    result = _graph(FakeClassifier(agent="ernaehrungsplaner"), runner).invoke({"audio": b"xx"})
    assert result["route"] == "hitl"
    assert result["awaiting_confirmation"] is True
    assert result["escalation_reason"] == "medizinische Frage"


def test_confirmation_yes_calls_server2():
    g = _graph(FakeClassifier(remote_needed=True))
    first = g.invoke({"audio": b"xx"})
    second = g.invoke({"confirmation": "Ja", "query": first["query"]})
    assert "[Großes Modell]" in second["answer"]
    assert second["awaiting_confirmation"] is False


def test_confirmation_no_stays_local():
    g = _graph(FakeClassifier(remote_needed=True))
    first = g.invoke({"audio": b"xx"})
    second = g.invoke({"confirmation": "Nein", "query": first["query"]})
    assert second["answer"] == "Alles klar, dann bleibe ich lokal."
    assert second["awaiting_confirmation"] is False
```

**Step 2: Ausführen** — `uv run pytest tests/test_graph.py -q` → muss fehlschlagen (Signatur + Nodes fehlen).

**Step 3: Implementieren** — `src/max/router/graph.py` komplett ersetzen:

```python
"""LangGraph-State-Maschine: Transkription → Sprecher → Klassifikation → Routing → Antwort.

Routing-Regeln (Subprojekt B):
- remote_needed (Klassifikator), niedrige Konfidenz (< 0.5) oder unbekannter Agent
  → HITL-Gate („respond_remote")
- bekannter Agent mit hoher Konfidenz → lokal: Fach-Agent via AgentRunner
- Agent-Selbst-Eskalation ([ESCALATE]) → dasselbe HITL-Gate

HITL-Gate: Die Frage (HITL_QUESTION) ist die Antwort des ersten Turns.
Die Bestätigungsrunde kommt als zweiter Graph-Aufruf (state["confirmation"]);
der Node „confirm" schaltet dann auf Server 2 (ja) oder bleibt lokal (nein).
"""
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from max.config import resolve_speaker
from max.router.classify import Classification
from max.router.hitl import HITL_QUESTION, is_confirmation


class State(TypedDict):
    audio: bytes
    text: str
    speaker: str
    agent: str
    confidence: float
    remote_needed: bool
    route: str
    answer: str
    query: str
    awaiting_confirmation: bool
    confirmation: str | None


def build_graph(transcriber, diarizer, registry, classifier, profiles, runner, server2):
    """Baut die State-Maschine.

    profiles: Liste von Agent-Profilen (dicts mit „name", „keywords", ...).
    runner: AgentRunner, der die Fach-Agenten ausführt.
    """
    agent_names = [p["name"] for p in profiles]

    def transcribe(state):
        text = transcriber.transcribe(state["audio"])
        segments = diarizer.diarize(state["audio"])
        speaker = resolve_speaker([s[0] for s in segments], registry)
        return {"text": text, "speaker": speaker, "query": text}

    def classify(state):
        try:
            c = classifier.classify(state["text"], agent_names)
        except Exception:
            # Fehlfall (z. B. ollama down) → sicher remote
            c = Classification("unknown", 0.0, True)
        return {"agent": c.agent, "confidence": c.confidence, "remote_needed": c.remote_needed}

    def route(state):
        if state["remote_needed"] or state["agent"] not in agent_names or state["confidence"] < 0.5:
            return "respond_remote"
        return "respond_local"

    def respond_local(state):
        profile = next((p for p in profiles if p["name"] == state["agent"]), None)
        if profile is None:
            return {"route": "hitl", "answer": HITL_QUESTION, "query": state["text"],
                    "awaiting_confirmation": True, "escalation_reason": "unbekannter Agent"}
        result = runner.run(profile, state["text"])
        if result.escalated:
            return {"route": "hitl", "answer": HITL_QUESTION, "query": state["text"],
                    "awaiting_confirmation": True, "escalation_reason": result.escalation_reason}
        return {"route": "local", "answer": result.answer, "awaiting_confirmation": False}

    def respond_remote(state):
        return {"route": "hitl", "answer": HITL_QUESTION, "query": state["text"],
                "awaiting_confirmation": True, "escalation_reason": "remote_needed"}

    def confirm(state):
        # Bestätigungsrunde: „Ja" schaltet Server 2 ein, sonst lokal bleiben
        if is_confirmation(state.get("confirmation") or ""):
            server2.wake()
            return {"answer": server2.ask(state.get("query", "")), "awaiting_confirmation": False}
        return {"answer": "Alles klar, dann bleibe ich lokal.", "awaiting_confirmation": False}

    def start_router(state):
        # Erster Turn enthält Audio, Bestätigungsrunde kommt ohne Audio
        if state.get("audio"):
            return "transcribe"
        return "confirm"

    g = StateGraph(State)
    g.add_node("transcribe", transcribe)
    g.add_node("classify", classify)
    g.add_node("respond_local", respond_local)
    g.add_node("respond_remote", respond_remote)
    g.add_node("confirm", confirm)
    g.add_conditional_edges(START, start_router, {"transcribe": "transcribe", "confirm": "confirm"})
    g.add_edge("transcribe", "classify")
    g.add_conditional_edges(
        "classify", route, {"respond_local": "respond_local", "respond_remote": "respond_remote"}
    )
    g.add_edge("respond_local", END)
    g.add_edge("respond_remote", END)
    g.add_edge("confirm", END)
    return g.compile()
```

**Step 4: Ausführen** — `uv run pytest tests/test_graph.py -q` → 8 passed.

**Step 5: Commit** — `git add -A && git commit -m "max: graph hitl + runner wiring"`

## Task 5: Ernährungsplaner (Definition + opencode-Konfiguration)

**Files:**
- `src/max/agents/nutrition.py` (neu)
- `config/agents/ernaehrungsplaner.yaml` (neu)
- `config/opencode/opencode.json` (neu)
- `config/opencode/ernaehrungsplaner.prompt.md` (neu)
- `config/agents/demo.yaml` (entfernen)
- `.gitignore` (`data/` ergänzen, falls noch nicht vorhanden)
- `tests/test_nutrition.py` (neu)

**Step 1: Failing test schreiben** — `tests/test_nutrition.py`:

```python
import os

from max.agents.nutrition import AGENT_NAME, nutrition_profile


def test_profile_fields():
    profile = nutrition_profile()
    assert profile["name"] == AGENT_NAME
    assert profile["runner"] == "opencode"
    assert "ernährung" in profile["keywords"]
    assert profile["memory_dir"] == "data/agents/ernaehrungsplaner"


def test_config_files_exist():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert os.path.exists(os.path.join(root, "config", "agents", "ernaehrungsplaner.yaml"))
    assert os.path.exists(os.path.join(root, "config", "opencode", "opencode.json"))
    assert os.path.exists(os.path.join(root, "config", "opencode", "ernaehrungsplaner.prompt.md"))
    # Demo-Agent wird vom Ernährungsplaner ersetzt
    assert not os.path.exists(os.path.join(root, "config", "agents", "demo.yaml"))
```

**Step 2: Ausführen** — `uv run pytest tests/test_nutrition.py -q` → muss fehlschlagen.

**Step 3: Implementieren**

`src/max/agents/nutrition.py`:

```python
"""Definition des Beispiel-Agenten „Ernährungsplaner" (Subprojekt B).

Dieses Modul liefert nur das Agent-Profil (Defaults). Der System-Prompt
lebt in config/opencode/ernaehrungsplaner.prompt.md und wird von
opencode.json referenziert — hier keine Duplizierung.

Die Plattform ist multi-agent tauglich: weitere Fach-Agenten folgen dem
selben Muster (YAML + prompt.md + opencode.json-Eintrag).
"""

# Agent-Name (ASCII-Identifier für die opencode CLI)
AGENT_NAME = "ernaehrungsplaner"


def nutrition_profile() -> dict:
    """Profil des Ernährungsplaners.

    Spiegelbild von config/agents/ernaehrungsplaner.yaml; das YAML ist die
    persistente Quelle, dieser dict ist das In-Memory-Äquivalent, das der
    Runner verwendet. memory_dir ist relativ zum Repo-Root.
    """
    return {
        "name": AGENT_NAME,
        "description": "Ernährungsplaner: plant Mahlzeiten, nutzt Mealie",
        "keywords": ["ernährung", "essen", "rezepte", "protein", "fitness", "plan"],
        "capabilities": ["meal plan", "recipes", "nutrition"],
        "runner": "opencode",
        "memory_dir": "data/agents/ernaehrungsplaner",
    }
```

`config/agents/ernaehrungsplaner.yaml`:

```yaml
name: ernährungsplaner
description: "Ernährungsplaner: plant Mahlzeiten, nutzt Mealie"
keywords: [ernährung, essen, rezepte, protein, fitness, plan]
capabilities: [meal plan, recipes, nutrition]
```

`config/opencode/ernaehrungsplaner.prompt.md`:

```markdown
# Ernährungsplaner

Du bist der Ernährungsplaner von Max, ein lokaler Sprachassistent.

## Aufgaben
- Erstelle Ernährungspläne, Mahlzeiten und Einkaufslisten.
- Nutze die Mealie-MCP-Tools (z. B. `get_todays_mealplan`, Rezepte, Kategorien),
  um aktuelle Mahlzeiten und bestehende Pläne zu berücksichtigen.
- Gib konkrete, alltagstaugliche Vorschläge (Mahlzeit, Mengen, Einkauf).

## Memory
Du hast zwei Memory-Dateien (die Pfade stehen in der Aufgabe):
- `profile.yaml`: strukturierte Angaben über die Person (Allergien, Ziele, Vorlieben)
- `memory.md`: freie Notizen (Gesprächshistorie, Korrekturen)

Speichere NEUE Informationen über die Person (z. B. Allergien, Kalorienziel,
Lieblingsgerichte) mit deinen Dateitools in diese Dateien, wenn sie noch nicht dort stehen.

## Eskalation
Wenn eine Aufgabe nur mit dem großen Modell (Server 2) sinnvoll lösbar ist
(z. B. medizinische, juristische oder sehr komplexe Fragen), antworte
AUSSCHLIESSLICH mit:
[ESCALATE] <kurze Begründung>
```

`config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "agent": {
    "ernaehrungsplaner": {
      "description": "Ernährungsplaner: plant Mahlzeiten und nutzt Mealie für den Tagesplan",
      "prompt": "{file:./ernaehrungsplaner.prompt.md}",
      "permission": {
        "read": "allow",
        "edit": "allow",
        "bash": "deny",
        "external_directory": "allow"
      }
    }
  },
  "mcp": {
    "mealie": {
      "type": "local",
      "command": ["uvx", "git+https://github.com/rldiao/mealie-mcp-server"]
    }
  }
}
```

Wichtig: `external_directory` muss erlaubt sein, damit der Agent die Memory-Dateien
in `data/agents/ernaehrungsplaner/` (außerhalb der opencode-Worktree `config/opencode/`)
lesen und schreiben kann. Die Mealie-Env-Variablen (`MEALIE_BASE_URL`, `MEALIE_API_KEY`)
werden vom Prozessumgebungsvariable geerbt, nicht im Repo gespeichert.

**Step 4: Ausführen** — `uv run pytest tests/test_nutrition.py -q` → 2 passed; `uv run pytest -q` → alles grün.

**Step 5: Commit** — `git add -A && git commit -m "max: ernährungsplaner agent + opencode config"`

## Task 6: main.py — HITL-Loop + Runner-Wiring

**Files:** `src/max/main.py` (Umschreiben)

**Step 1: Implementieren** — `src/max/main.py` komplett ersetzen:

```python
import os
import numpy as np

from max.agents.runner import OpencodeRunner
from max.config import load_agent_profiles, load_speakers
from max.pipeline.diarization import PyannoteDiarizer
from max.pipeline.stt import WhisperTranscriber
from max.pipeline.vad import SAMPLE_RATE, frame_bytes, Vad
from max.remote.server2 import MockServer2
from max.router.classify import OllamaClassifier
from max.router.graph import build_graph
from max.tts.kokoro_tts import KokoroTts


def capture_audio(vad: Vad, max_seconds: float = 30.0, end_silence_frames: int = 5):
    import sounddevice as sd

    frames = []
    in_speech = False
    silent_run = 0
    max_frames = int(max_seconds * 1000 / 30)
    block = frame_bytes // 2
    with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=block) as stream:
        while len(frames) < max_frames:
            frame, _ = stream.read(block)
            data = frame.tobytes()
            if vad.is_speech(data):
                frames.append(data)
                in_speech = True
                silent_run = 0
            elif in_speech:
                silent_run += 1
                if silent_run >= end_silence_frames:
                    break
    if not in_speech:
        return None
    return b"".join(frames)


def speak(tts, text: str) -> None:
    """Spricht Text per TTS (sounddevice wird lazy importiert)."""
    import sounddevice as sd

    for chunk in tts.synthesize_chunks(text):
        sd.play(np.frombuffer(chunk, dtype=np.int16), 22050)
        sd.wait()


def main():
    import sounddevice as sd  # noqa: F841 — sicher, dass der Import am Start funktioniert

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    registry = load_speakers(os.path.join(root, "config", "speakers.yaml"))
    profiles = load_agent_profiles(os.path.join(root, "config", "agents"))
    runner = OpencodeRunner(opencode_dir=os.path.join(root, "config", "opencode"))
    transcriber = WhisperTranscriber()
    graph = build_graph(
        transcriber,
        PyannoteDiarizer(),
        registry,
        OllamaClassifier(os.environ.get("MAX_OLLAMA_MODEL", "qwen2.5:9b")),
        profiles,
        runner,
        MockServer2(),
    )
    vad = Vad()
    tts = KokoroTts()
    while True:
        audio = capture_audio(vad)
        if audio is None:
            continue
        result = graph.invoke({"audio": audio})

        # HITL-Gate: remote-Routing braucht eine Sprachbestätigung des Users
        if result["awaiting_confirmation"]:
            print(f"[Max]: {result['answer']}")
            speak(tts, result["answer"])
            confirm_audio = capture_audio(vad)
            if confirm_audio is None:
                continue  # keine Bestätigung → remote-Routing verworfen
            confirm_text = transcriber.transcribe(confirm_audio)
            result = graph.invoke({
                "confirmation": confirm_text,
                "query": result["query"],
                "speaker": result["speaker"],
            })

        print(f"[Max] ({result['speaker']}): {result['answer']}")
        speak(tts, result["answer"])


if __name__ == "__main__":
    main()
```

**Step 2: Verifizieren** — `uv run python -m py_compile src/max/main.py` → clean; `uv run pytest -q` → alles grün.

**Step 3: Commit** — `git add -A && git commit -m "max: main hitl loop + runner wiring"`

## Task 7: E2E-Smoke-Test (offline)

**Files:** `tests/test_e2e.py` (Umschreiben)

**Step 1: Implementieren** — `tests/test_e2e.py` komplett ersetzen:

```python
from max.agents.runner import MockAgentRunner
from max.remote.server2 import MockServer2
from max.router.graph import build_graph
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def _profiles():
    return [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}]


def test_e2e_local_flow():
    g = build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                    FakeClassifier(agent="ernaehrungsplaner"), _profiles(),
                    MockAgentRunner(), MockServer2())
    result = g.invoke({"audio": b"synthetic-audio"})
    assert result["speaker"] == "Alex"
    assert result["route"] == "local"
    assert result["answer"] == "Mock-Antwort zu: Testfrage"


def test_e2e_extended_mode_flow():
    g = build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                    FakeClassifier(remote_needed=True), _profiles(),
                    MockAgentRunner(), MockServer2())
    first = g.invoke({"audio": b"synthetic-audio"})
    assert first["route"] == "hitl"
    assert first["awaiting_confirmation"] is True
    second = g.invoke({"confirmation": "Ja", "query": first["query"]})
    assert "[Großes Modell]" in second["answer"]
    assert second["awaiting_confirmation"] is False


def test_e2e_declined_remote_flow():
    g = build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                    FakeClassifier(remote_needed=True), _profiles(),
                    MockAgentRunner(), MockServer2())
    g.invoke({"audio": b"synthetic-audio"})
    second = g.invoke({"confirmation": "Nein", "query": "Testfrage"})
    assert second["answer"] == "Alles klar, dann bleibe ich lokal."
```

**Step 2: Ausführen** — `uv run pytest tests/test_e2e.py -q` → 3 passed.

**Step 3: Commit** — `git add -A && git commit -m "max: e2e smoke hitl flows"`

## Task 8: Vollständige Verifikation + Finaler Commit

**Step 1:** `uv run pytest -q` → alle Tests grün (Memory, Runner, HITL, Nutrition, Graph, E2E, bestehende Pipeline-Tests).

**Step 2:** `uv run python -m py_compile src/max/main.py` → clean.

**Step 3:** `git status` prüfen; `git add -A && git commit -m "max: agent platform (subprojekt B)"` falls noch Änderungen übrig sind.

**Step 4:** Ergebnis in `.superpowers/sdd/2026-08-25-max-walking-skeleton/progress.md` erfassen (sowie offene Punkte Subprojekt A: Task 11 Re-Review, Tasks 12–13).
