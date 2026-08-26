# Max Memory-Personalisierung + System-Test Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Subprojekt F: gemeinsames Personen-Profil (person.yaml), Onboarding-Interview-Mode im Graph, Person-Kontext in Task-Prompts, Smoke-Test mit simuliertem Audio.

**Architecture:** PersonMemory (read-only Python, Agent schreibt via opencode Dateitools) + interview_mode-State im Graph + `[ASK]`/`[DONE]`-Marker + Smoke-Test-CLI.

**Tech Stack:** Python 3.11+, stdlib + yaml, langgraph, pytest. Keine neuen Dependencies.

## Conventions
- German docstrings, commit style `max: <desc>`, TDD (test first, then implementation).
- Neue Komponenten: stdlib-only (yaml bereits vorhanden).

---

## Task 1: PersonMemory

**Files:**
- Create: `src/max/agents/person.py`
- Create: `tests/test_person.py`

### 1.1 Write failing tests (`tests/test_person.py`)

```python
from max.agents.person import PersonMemory


def test_read_missing(tmp_path):
    mem = PersonMemory(str(tmp_path / "person.yaml"))
    assert mem.read() == {}


def test_write_category_roundtrip(tmp_path):
    mem = PersonMemory(str(tmp_path / "person.yaml"))
    mem.write_category("allergien", ["Milch"])
    mem.write_category("ziele", "80g Protein")
    assert mem.read() == {"allergien": ["Milch"], "ziele": "80g Protein"}


def test_get_context_empty(tmp_path):
    mem = PersonMemory(str(tmp_path / "person.yaml"))
    assert mem.get_context() == "(noch keine Erinnerungen)"


def test_get_context_with_profile(tmp_path):
    mem = PersonMemory(str(tmp_path / "person.yaml"))
    mem.write_category("allergien", ["Milch"])
    context = mem.get_context()
    assert "Personen-Profil:" in context
    assert "allergien" in context
```

Run: `uv run pytest tests/test_person.py -v` → FAIL (ModuleNotFound).

### 1.2 Implementation (`src/max/agents/person.py`)

```python
"""Gemeinsames Personen-Profil (Subprojekt F).

Ein strukturiertes Profil der Person (Allergien, Ziele, Vorlieben,
Beschränkungen), das von allen Agenten geteilt wird. Die Datei liegt in
data/memory/person.yaml (Pfad via Constructor). Die Agenten schreiben die
Datei per opencode-Dateitools; der Python-Runner liest sie und injiziert den
Kontext in die Task-Prompts.
"""
import os

import yaml


class PersonMemory:
    """Datei-Personen-Profil: person.yaml."""

    def __init__(self, path: str):
        self.path = path

    def read(self) -> dict:
        """Liest person.yaml; existiert die Datei nicht, leeres dict."""
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def write_category(self, key: str, value) -> None:
        """Schreibt eine Kategorie in person.yaml (idempotent)."""
        profile = self.read()
        profile[key] = value
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.safe_dump(profile, f, allow_unicode=True, sort_keys=False)

    def get_context(self) -> str:
        """Personen-Profil als kompakten Kontext-Text für Task-Prompts."""
        profile = self.read()
        if not profile:
            return "(noch keine Erinnerungen)"
        lines = ["Personen-Profil:"]
        for key, value in profile.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)
```

### 1.3 Verify
`uv run pytest tests/test_person.py -v` → 4 tests PASS.

### 1.4 Commit
`git add src/max/agents/person.py tests/test_person.py && git commit -m "max: PersonMemory für gemeinsames Personen-Profil"`

---

## Task 2: Runner-Extension (Person-Kontext)

**Files:**
- Modify: `src/max/agents/runner.py`
- Modify: `tests/test_runner.py`

### 2.1 Write failing tests (append to `tests/test_runner.py`)

```python
def test_build_task_message_with_person():
    msg = build_task_message(
        "Plane eine Woche",
        "Profil: sport: Krafttraining",
        person_context="Personen-Profil:\n  allergien: ['Milch']",
        person_path="/data/memory/person.yaml",
    )
    assert "Personen-Profil:\n  allergien: ['Milch']" in msg
    assert "/data/memory/person.yaml" in msg


def test_opencode_runner_with_person_memory(tmp_path):
    script = tmp_path / "fake-opencode"
    script.write_text("#!/bin/sh\nprintf 'Alles klar'\n", encoding="utf-8")
    os.chmod(script, 0o755)
    person = PersonMemory(str(tmp_path / "person.yaml"))
    person.write_category("allergien", ["Milch"])
    runner = OpencodeRunner(
        opencode_bin=str(script), opencode_dir=str(tmp_path),
        timeout=10.0, person_memory=person,
    )
    result = runner.run(
        {"name": "x", "memory_dir": str(tmp_path / "mem"),
         "person_path": str(tmp_path / "person.yaml")},
        "Aufgabe",
    )
    assert result.answer == "Alles klar"
    assert result.escalated is False
```

(Need `from max.agents.person import PersonMemory` in test file.)

### 2.2 Implementation (`src/max/agents/runner.py`)

`build_task_message(task, memory_context, person_context="", card_path=None, person_path=None)`:

```python
def build_task_message(task: str, memory_context: str, person_context: str = "",
                       card_path: str | None = None, person_path: str | None = None) -> str:
    """Setzt den Task-Prompt aus Nutzeranfrage, Memory- und Personen-Kontext zusammen.

    Enthält die Anweisung zur strukturierten Eskalation. Mit card_path erhält
    der Agent die Anweisung, eine Display-Card zu schreiben. Mit person_path
    erhält er die Anweisung, neue dauerhafte Fakten ins Personen-Profil eintragen.
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
            f"\n\n## Display-Card\n"
            f"Schreibe für die Display-Card eine Datei mit dem Namen {card_path} in "
            f"das Verzeichnis /home/user/max/cards. Es gibt dort bereits eine "
            f"README.md, die das Format erklärt."
        )
    return message
```

`OpencodeRunner.__init__` gets `person_memory=None`:

```python
def __init__(self, opencode_bin: str | None = None, opencode_dir: str | None = None,
             timeout: float = 120.0, person_memory=None):
    ...
    self.person_memory = person_memory
```

In `run()`:

```python
person_context = self.person_memory.get_context() if self.person_memory is not None else ""
person_path = agent_profile.get("person_path")
if person_path:
    person_path = self._resolve_path(person_path)
...
prompt = build_task_message(task, memory.get_context(), person_context, card_path, person_path)
```

### 2.3 Verify
`uv run pytest tests/test_runner.py -v` → all PASS (existing + 2 new).

### 2.4 Commit
`git commit -m "max: Runner injiziert Personen-Profil-Kontext und person_path"`

---

## Task 3: Onboarding-Agent-Config

**Files:**
- Create: `config/agents/onboarding.yaml`
- Create: `config/opencode/onboarding.prompt.md`
- Modify: `config/opencode/opencode.json`
- Modify: `tests/test_config.py`

### 3.1 Write failing tests (append to `tests/test_config.py`)

```python
def test_onboarding_profile():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profiles = load_agent_profiles(os.path.join(root, "config", "agents"))
    names = [p["name"] for p in profiles]
    assert "onboarding" in names
    ob = next(p for p in profiles if p["name"] == "onboarding")
    assert ob["person_path"] == "data/memory/person.yaml"
    assert "onboarding" in ob["keywords"]


def test_opencode_json_has_onboarding():
    import json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = json.loads(open(os.path.join(root, "config", "opencode", "opencode.json"),
                          encoding="utf-8").read())
    assert "onboarding" in cfg["agent"]
```

### 3.2 Config files

`config/agents/onboarding.yaml`:

```yaml
name: onboarding
description: "Onboarding: befüllt das gemeinsame Personen-Profil per Interview"
keywords: [onboarding, interview, profil, kennenlernen, lernen]
capabilities: [person profile, onboarding interview]
memory_dir: data/agents/onboarding
person_path: data/memory/person.yaml
```

`config/opencode/onboarding.prompt.md`:

```markdown
# Onboarding

Du bist der Onboarding-Agent von Max. Du führst ein kurzes Interview mit der Person
und trägst die Informationen in das gemeinsame Personen-Profil ein.

## Interview-Regeln
- Stelle pro Turn max. 3 gezielte Fragen (Allergien, Ziele, Vorlieben, Beschränkungen).
- Antworte kurz und alltagstauglich (die Antwort wird per Sprachausgabe gesprochen).
- Trage nach jedem Turn die neuen Informationen strukturiert als YAML in die
  Personen-Profil-Datei aus der Aufgabe ein.
- Kategorien: allergien, ziele, vorlieben, beschränkungen.
- Bestehende Einträge ergänzen, nicht überschreiben; keine Duplikate.

## Marker (am Ende deiner Antwort)
- Wenn weitere Fragen folgen, endet die Antwort mit: [ASK]
- Wenn das Interview beendet ist, endet die Antwort mit: [DONE]
```

`opencode.json`: add under `"agent"`:

```json
"onboarding": {
  "description": "Onboarding: befüllt das gemeinsame Personen-Profil per Interview",
  "prompt": "{file:./onboarding.prompt.md}",
  "permission": {
    "read": "allow",
    "edit": "allow",
    "bash": "deny",
    "external_directory": "allow"
  }
}
```

### 3.3 Verify
`uv run pytest tests/test_config.py -v` → all PASS.

### 3.4 Commit
`git commit -m "max: Onboarding-Agent-Config (yaml, prompt, opencode.json)"`

---

## Task 4: Graph Interview-Mode + main.py Wiring

**Files:**
- Modify: `src/max/router/graph.py`
- Modify: `src/max/main.py`
- Modify: `tests/test_graph.py`

### 4.1 Write failing tests (append to `tests/test_graph.py`)

```python
class FakeInterviewRunner:
    """Erster Turn: Frage + [ASK], zweiter Turn: Abschluss + [DONE]."""
    def __init__(self):
        self.calls = 0

    def run(self, agent_profile, task):
        self.calls += 1
        if self.calls == 1:
            return AgentResult(answer="Wie sind deine Allergien? [ASK]")
        return AgentResult(answer="Alles notiert [DONE]")


def _graph_interview(runner):
    profiles = [{"name": "onboarding", "keywords": ["onboarding"], "memory_dir": "x"}]
    return build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                       FakeClassifier(agent="onboarding"), profiles, runner, MockServer2())


def test_interview_mode_continues():
    runner = FakeInterviewRunner()
    g = _graph_interview(runner)
    first = g.invoke({"audio": b"xx"})
    assert first["interview_mode"] is True
    assert "[ASK]" not in first["answer"]
    assert runner.calls == 1
    second = g.invoke({"audio": b"xx", "interview_mode": True})
    assert second["interview_mode"] is False
    assert "[DONE]" not in second["answer"]
    assert runner.calls == 2


def test_interview_no_marker_ends():
    runner = MockAgentRunner(answer="Interview fertig")
    g = _graph_interview(runner)
    result = g.invoke({"audio": b"xx"})
    assert result["interview_mode"] is False
```

(Need `from max.agents.runner import AgentResult, MockAgentRunner` imports.)

### 4.2 Implementation (`src/max/router/graph.py`)

State TypedDict: add `interview_mode: bool`.

Constants:

```python
ASK_MARKER = "[ASK]"
DONE_MARKER = "[DONE]"
MAX_INTERVIEW_TURNS = 10
```

New node:

```python
def interview(state):
    profile = next((p for p in profiles if p["name"] == "onboarding"), None)
    if profile is None:
        return {"route": "hitl", "answer": "Das Onboarding kann ich leider nicht durchführen.",
                "query": state["text"], "awaiting_confirmation": False,
                "interview_mode": False}
    _start("agent")
    result = runner.run(profile, state["text"])
    _end("agent")
    _tel_tokens("agent", result.answer)
    answer = result.answer
    interview_mode = False
    if result.escalated:
        answer = "Das Onboarding kann ich leider nicht durchführen."
    else:
        if ASK_MARKER in answer:
            interview_mode = True
            answer = answer.replace(ASK_MARKER, "").strip()
        if DONE_MARKER in answer:
            answer = answer.replace(DONE_MARKER, "").strip()
    return {"route": "local", "answer": answer, "awaiting_confirmation": False,
            "interview_mode": interview_mode}
```

Edges: replace `g.add_edge("transcribe", "classify")` with:

```python
def post_transcribe(state):
    if state.get("interview_mode"):
        return "interview"
    return "classify"

g.add_conditional_edges("transcribe", post_transcribe,
                        {"interview": "interview", "classify": "classify"})
g.add_edge("interview", END)
```

### 4.3 main.py wiring

In the pipeline loop, track interview state:

```python
from max.router.graph import build_graph, MAX_INTERVIEW_TURNS
...
interview_mode = False
interview_turns = 0
...
if interview_mode:
    result = graph.invoke({"audio": audio, "interview_mode": True})
    interview_turns += 1
else:
    result = graph.invoke({"audio": audio})
...
if result.get("interview_mode"):
    interview_mode = True
    if interview_turns > MAX_INTERVIEW_TURNS:
        interview_mode = False
else:
    interview_mode = False
    interview_turns = 0
```

### 4.4 Verify
`uv run pytest tests/test_graph.py tests/test_main_wiring.py -v` → all PASS.

### 4.5 Commit
`git commit -m "max: Interview-Mode im Graph (ASK/DONE) + main.py-Wiring"`

---

## Task 5: Smoke-Test (simulated audio)

**Files:**
- Create: `src/max/smoke.py`
- Create: `scripts/system_test.py`
- Create: `tests/test_smoke.py`

### 5.1 Write failing test (`tests/test_smoke.py`)

```python
from max.agents.runner import MockAgentRunner
from max.remote.server2 import MockServer2
from max.smoke import run_smoke
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


class FakeTts:
    def synthesize_chunks(self, text: str) -> list[bytes]:
        return [b"xx"]


def test_smoke_local(tmp_path):
    profiles = [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}]
    summary = run_smoke(
        b"xx", FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
        FakeClassifier(agent="ernaehrungsplaner"), profiles, MockAgentRunner(),
        MockServer2(), tts=FakeTts(), store_path=str(tmp_path / "t.db"),
    )
    assert summary["route"] == "local"
    assert summary["speaker"] == "Alex"
    assert summary["tts_bytes"] == 2
    assert summary["telemetry_recorded"] is True
```

### 5.2 Implementation (`src/max/smoke.py`)

```python
"""Smoke-Test der Pipeline (Subprojekt F).

run_smoke() führt ein Audio-Byte-Array durch den kompletten Graph
(Transkription → Routing → Agent → Antwort), synthetisiert die Antwort
per TTS (Bytes statt Playback) und zeichnet einen Telemetrie-Record.
Kein Mikrofon nötig — das Audio kommt als Bytes (z. B. WAV) von außen.
"""
from max.router.graph import build_graph
from max.telemetry.recorder import TelemetryRecorder
from max.telemetry.store import TelemetryStore


def run_smoke(audio: bytes, transcriber, diarizer, registry, classifier, profiles,
              runner, server2, tts=None, store_path: str | None = None) -> dict:
    """Führt eine Pipeline-Runde aus und liefert eine Stage-by-Stage-Übersicht."""
    recorder = TelemetryRecorder()
    store = TelemetryStore(store_path) if store_path else None
    graph = build_graph(transcriber, diarizer, registry, classifier, profiles, runner,
                        server2, recorder=recorder)
    result = graph.invoke({"audio": audio})

    summary = {
        "text": result.get("text", ""),
        "speaker": result.get("speaker", ""),
        "agent": result.get("agent", ""),
        "route": result.get("route", ""),
        "answer": result.get("answer", ""),
        "awaiting_confirmation": result.get("awaiting_confirmation", False),
    }
    if tts is not None:
        summary["tts_bytes"] = len(b"".join(tts.synthesize_chunks(result.get("answer", ""))))
    if store is not None:
        store.record(recorder.build(
            speaker=result.get("speaker", ""),
            text=result.get("text", result.get("query", "")),
            agent=result.get("agent", ""),
            remote_needed=bool(result.get("remote_needed", False)),
        ))
        summary["telemetry_recorded"] = True
        store.close()
    return summary
```

### 5.3 CLI (`scripts/system_test.py`)

```python
"""Smoke-Test-CLI: ein Audio-Input durch die komplette Pipeline.

Usage:
  uv run python scripts/system_test.py --mock
  uv run python scripts/system_test.py --real --audio /pfad/zur.wav

--mock: Offline-Komponenten (Fake-Transkription, Mock-Runner), deterministisch,
         keine Modelle nötig.
--real: Echte Pipeline (Whisper, Pyannote, Ollama, opencode-Runner, Kokoro-TTS).
         Braucht: ollama (MAX_OLLAMA_MODEL), opencode, Kokoro. Audio: WAV-Datei.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from max.smoke import run_smoke


class FakeTranscriber:
    def transcribe(self, audio):
        return "Plane mir einen Ernährungsplan"


class FakeDiarizer:
    def diarize(self, audio):
        return [("SPEAKER_00", 0.0, 1.0)]


class FakeClassifier:
    def classify(self, text, agents):
        from max.router.classify import Classification
        return Classification("ernaehrungsplaner", 0.9, False)


class FakeTts:
    def synthesize_chunks(self, text):
        return [b"xx" * max(1, len(text.split()))]


def main():
    parser = argparse.ArgumentParser(description="Max Smoke-Test")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--audio", default=None)
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if args.real:
        if not args.audio:
            print("Fehler: --real braucht --audio <wav>")
            sys.exit(1)
        with open(args.audio, "rb") as f:
            audio = f.read()
        from max.agents.runner import OpencodeRunner
        from max.pipeline.diarization import PyannoteDiarizer
        from max.pipeline.stt import WhisperTranscriber
        from max.router.classify import OllamaClassifier
        from max.tts.kokoro_tts import KokoroTts
        from max.config import load_agent_profiles
        from max.remote.server2 import MockServer2
        transcriber = WhisperTranscriber()
        diarizer = PyannoteDiarizer()
        classifier = OllamaClassifier(os.environ.get("MAX_OLLAMA_MODEL", "qwen3.5:9b"))
        profiles = load_agent_profiles(os.path.join(root, "config", "agents"))
        runner = OpencodeRunner(opencode_dir=os.path.join(root, "config", "opencode"))
        server2 = MockServer2()
        tts = KokoroTts()
    else:
        audio = b"xx"
        from max.agents.runner import MockAgentRunner
        from max.remote.server2 import MockServer2
        profiles = [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}]
        transcriber = FakeTranscriber()
        diarizer = FakeDiarizer()
        classifier = FakeClassifier()
        runner = MockAgentRunner()
        server2 = MockServer2()
        tts = FakeTts()

    registry = [{"name": "Alex"}]
    store_path = os.path.join(root, "data", "smoke_test.db")
    summary = run_smoke(audio, transcriber, diarizer, registry, classifier, profiles,
                        runner, server2, tts=tts, store_path=store_path)
    print("=== Smoke-Test Summary ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("OK")


if __name__ == "__main__":
    main()
```

### 5.4 Verify
`uv run pytest tests/test_smoke.py -v` → PASS.
`uv run python scripts/system_test.py --mock` → "OK".

### 5.5 Commit
`git commit -m "max: Smoke-Test (Pipeline-Orchestrierung + CLI)"`

---

## Task 6: Final Verification

1. `uv run pytest -v` → ALL PASS (existing 113 + new tests).
2. `uv run python scripts/system_test.py --mock` → OK.
3. Commit any remaining fixes.

## Notes
- Real 2-machine test: cannot run yet (machines not connected). Smoke test validates pipeline offline.
- Ollama model: use `MAX_OLLAMA_MODEL=qwen3.5:9b` (local model name, not qwen2.5:9b default).
