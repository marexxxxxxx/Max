# Max Walking Skeleton (Subprojekt A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end Voice-Pipeline aufbauen: Mic → VAD → STT + Speaker-Recognition → LangGraph-Router (kleines ollama-Modell) → Demo-Agent → Kokoro Chunk-Streaming-TTS, plus Server-2-Stub (Mock-Wake + Mock-Antwort).

**Architecture:** Ein Python-Service auf Server 1. Isolierte Module mit Constructor-Injection, damit Unit-Tests ohne GPU/Modelle/Mic laufen. LangGraph-State-Machine: idle → listening → transcribe → classify → route_local|route_remote → respond → tts → idle.

**Tech Stack:** Python 3.12, uv, faster-whisper, pyannote-audio, Kokoro, LangGraph, ollama (Python-Client), webrtc-vad, sounddevice, PyYAML, pytest.

**Spec:** /home/user/max/docs/superpowers/specs/2026-08-25-max-design.md

## Global Constraints

- Python 3.12; Projekt-Root `/home/user/max`; Venv via uv (`uv venv` + `uv pip install`).
- Schwere Imports (faster-whisper, pyannote, kokoro, sounddevice, ollama) nur lazy (in Methoden) oder hinter Fakes, damit Unit-Tests ohne Download/GPU laufen.
- Alle Nutzer-zugehörigen Strings auf Deutsch.
- Konfiguration via YAML: `config/speakers.yaml`, `config/agents/*.yaml`.
- Tests müssen ohne Netzwerk/GPU/Mic bestehen (Fakes); E2E-Smoke ebenfalls mit Fakes.
- Router-Entscheidung: `remote_needed=true` ODER `confidence < 0.5` ODER Agent unbekannt → `route_remote`; sonst `route_local`.
- ollama-Modellname via Env `MAX_OLLAMA_MODEL`, Default `qwen2.5:9b`.

## File Structure

```
/home/user/max/
├── pyproject.toml
├── config/
│   ├── speakers.yaml
│   └── agents/
│       └── demo.yaml
├── src/max/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── vad.py
│   │   ├── stt.py
│   │   └── diarization.py
│   ├── router/
│   │   ├── __init__.py
│   │   ├── classify.py
│   │   └── graph.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── registry.py
│   │   └── demo_agent.py
│   ├── tts/
│   │   ├── __init__.py
│   │   └── kokoro_tts.py
│   └── remote/
│       ├── __init__.py
│       └── server2.py
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_vad.py
    ├── test_classify.py
    ├── test_agents.py
    ├── test_tts.py
    ├── test_remote.py
    ├── test_graph.py
    └── test_e2e.py
```

---

### Task 1: Projekt-Gerüst (Scaffold)

**Files:**
- Create: `pyproject.toml`, `src/max/__init__.py` + alle `__init__.py` in Subpackages, `tests/__init__.py` (optional)

- [ ] **Step 1: pyproject.toml schreiben**

```toml
[project]
name = "max"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "faster-whisper>=1.0",
  "pyannote.audio>=3.1",
  "kokoro>=0.2",
  "langgraph>=0.2",
  "ollama>=0.4",
  "sounddevice>=0.13",
  "webrtcvad>=2.0",
  "PyYAML>=6.0",
  "numpy>=1.24",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Verzeichnisstruktur + leere `__init__.py` anlegen**

```
cd /home/user/max
mkdir -p config/agents src/max/pipeline src/max/router src/max/agents src/max/tts src/max/remote tests
touch src/max/__init__.py src/max/pipeline/__init__.py src/max/router/__init__.py src/max/agents/__init__.py src/max/tts/__init__.py src/max/remote/__init__.py
```

- [ ] **Step 3: Venv + Dependencies installieren**

```
cd /home/user/max && uv venv && uv pip install -e ".[dev]"
```

- [ ] **Step 4: pytest verifizieren (noch keine Tests)**

```
cd /home/user/max && .venv/bin/python -m pytest
```
Expected: `no tests ran` (kein Fehler).

- [ ] **Step 5: Commit**

```
git add max/ && git commit -m "max: scaffold (pyproject, layout, uv env)"
```

### Task 2: Konfiguration (Speakers + Agent-Profile)

**Files:**
- Create: `config/speakers.yaml`, `config/agents/demo.yaml`, `src/max/config.py`, `tests/test_config.py`

- [ ] **Step 1: Failing Test schreiben** `tests/test_config.py`

```python
from max.config import load_speakers, load_agent_profiles, resolve_speaker

def test_load_speakers(tmp_path):
    p = tmp_path / "speakers.yaml"
    p.write_text('speakers:\n  - name: Alex\n  - name: Sam\n', encoding="utf-8")
    reg = load_speakers(str(p))
    assert [s["name"] for s in reg] == ["Alex", "Sam"]

def test_load_agent_profiles(tmp_path):
    f = tmp_path / "demo.yaml"
    f.write_text('name: demo-agent\nkeywords: [demo]\n', encoding="utf-8")
    prof = load_agent_profiles(str(tmp_path))
    assert prof[0]["name"] == "demo-agent"

def test_resolve_speaker_single():
    reg = [{"name": "Alex"}]
    assert resolve_speaker(["SPEAKER_00"], reg) == "Alex"

def test_resolve_speaker_multiple():
    reg = [{"name": "Alex"}]
    assert resolve_speaker(["SPEAKER_00", "SPEAKER_01"], reg) == "unbekannt"
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

```
cd /home/user/max && .venv/bin/python -m pytest tests/test_config.py -v
```
Expected: FAIL (ImportError).

- [ ] **Step 3: Implementieren** `src/max/config.py`

```python
from __future__ import annotations
from pathlib import Path
import yaml


def load_speakers(path: str) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data.get("speakers", [])


def load_agent_profiles(directory: str) -> list[dict]:
    d = Path(directory)
    return [yaml.safe_load(f.read_text(encoding="utf-8"))
            for f in sorted(d.glob("*.yaml"))]


def resolve_speaker(speaker_ids: list[str], registry: list[dict]) -> str:
    unique = sorted(set(speaker_ids))
    if len(unique) == 1 and len(registry) >= 1:
        return registry[0]["name"]
    return "unbekannt"
```

- [ ] **Step 4: YAML-Dateien anlegen**

`config/speakers.yaml`:
```yaml
speakers:
  - name: Alex
```

`config/agents/demo.yaml`:
```yaml
name: demo-agent
description: "Demo-Agent für den Walking Skeleton"
keywords: [demo, test]
capabilities: [echo]
```

- [ ] **Step 5: Tests verifizieren + Commit**

```
cd /home/user/max && .venv/bin/python -m pytest tests/test_config.py -v && git add max/ && git commit -m "max: config loading + speaker resolution"
```

### Task 3: VAD-Wrapper

**Files:**
- Create: `src/max/pipeline/vad.py`, `tests/test_vad.py`

- [ ] **Step 1: Failing Test** `tests/test_vad.py`

```python
import numpy as np
from max.pipeline.vad import Vad, frame_bytes

def _pcm(freq: float, silent: bool = False) -> bytes:
    n = 16000 * 30 // 1000
    t = np.arange(n) / 16000
    samples = np.zeros(n) if silent else 0.3 * np.sin(2 * np.pi * freq * t)
    return (samples * 32767).astype(np.int16).tobytes()

def test_speech_detected():
    assert Vad().is_speech(_pcm(440))

def test_silence_not_detected():
    assert not Vad().is_speech(_pcm(440, silent=True))

def test_frame_bytes():
    assert frame_bytes == 960  # 30 ms @ 16 kHz int16
```

- [ ] **Step 2: Fehlschlag verifizieren** → `.venv/bin/python -m pytest tests/test_vad.py -v` (FAIL)

- [ ] **Step 3: Implementieren** `src/max/pipeline/vad.py`

```python
import webrtcvad

SAMPLE_RATE = 16000
FRAME_MS = 30
frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2


class Vad:
    def __init__(self, aggressiveness: int = 2):
        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, SAMPLE_RATE)
```

- [ ] **Step 4: Verifizieren + Commit** → `pytest tests/test_vad.py -v`, dann `git add max/ && git commit -m "max: VAD wrapper (webrtc-vad)"`

### Task 4: STT-Wrapper (faster-whisper, lazy Import)

**Files:**
- Create: `src/max/pipeline/stt.py`, `tests/test_stt.py`

- [ ] **Step 1: Failing Test** `tests/test_stt.py`

```python
import pytest
from max.pipeline.stt import WhisperTranscriber

def test_lazy_no_model_on_init():
    t = WhisperTranscriber()
    assert t._model is None

def test_transcribe_with_fake_model(monkeypatch):
    class FakeModel:
        def transcribe(self, audio):
            return ([type("S", (), {"text": "Hallo Welt"})()], None)
    monkeypatch.setattr(WhisperTranscriber, "_ensure", lambda self: FakeModel())
    assert WhisperTranscriber().transcribe(b"audio") == "Hallo Welt"
```

- [ ] **Step 2: Fehlschlag verifizieren** → `.venv/bin/python -m pytest tests/test_stt.py -v` (FAIL)

- [ ] **Step 3: Implementieren** `src/max/pipeline/stt.py`

```python
class WhisperTranscriber:
    def __init__(self, model_size: str = "small", language: str = "de"):
        self.model_size = model_size
        self.language = language
        self._model = None

    def _ensure(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, language=self.language)
        return self._model

    def transcribe(self, audio: bytes) -> str:
        segments, _ = self._ensure().transcribe(audio, language=self.language)
        return " ".join(s.text for s in segments).strip()
```

- [ ] **Step 4: Verifizieren + Commit** → `pytest tests/test_stt.py -v`, dann `git add max/ && git commit -m "max: faster-whisper STT wrapper (lazy)"`

### Task 5: Diarization-Wrapper (pyannote, lazy Import)

**Files:**
- Create: `src/max/pipeline/diarization.py`, `tests/test_diarization.py`

- [ ] **Step 1: Failing Test** `tests/test_diarization.py`

```python
import numpy as np
from max.pipeline.diarization import PyannoteDiarizer

def test_lazy_no_pipeline_on_init():
    assert PyannoteDiarizer()._pipe is None

def test_diarize_with_fake_pipeline(monkeypatch):
    class FakeDiag:
        def itertracks(self, yield_label=True):
            return iter([("single", "SPEAKER_00", 0.0, 1.5)])
    class FakePipeline:
        def __call__(self, audio):
            return FakeDiag()
    d = PyannoteDiarizer()
    d._pipe = FakePipeline()
    segs = d.diarize(np.zeros(1600, dtype=np.int16).tobytes())
    assert segs == [("SPEAKER_00", 0.0, 1.5)]
```

- [ ] **Step 2: Fehlschlag verifizieren** → `pytest tests/test_diarization.py -v` (FAIL)

- [ ] **Step 3: Implementieren** `src/max/pipeline/diarization.py`

```python
class PyannoteDiarizer:
    def __init__(self):
        self._pipe = None

    def _ensure(self):
        if self._pipe is None:
            from pyannote.audio import Pipeline
            self._pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.0")
        return self._pipe

    def diarize(self, audio: bytes) -> list[tuple[str, float, float]]:
        import numpy as np
        data = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        diarization = self._ensure()(data)
        return [(spk, start, end)
                for _, spk, start, end in diarization.itertracks(yield_label=True)]
```

- [ ] **Step 4: Verifizieren + Commit** → `pytest tests/test_diarization.py -v`, dann `git add max/ && git commit -m "max: pyannote diarization wrapper (lazy)"`

### Task 6: Klassifikator (ollama, strukturierte Ausgabe)

**Files:**
- Create: `src/max/router/classify.py`, `tests/test_classify.py`

- [ ] **Step 1: Failing Tests** `tests/test_classify.py`

```python
from max.router.classify import parse_classification, OllamaClassifier

def test_parse_valid():
    raw = '{"agent": "demo-agent", "confidence": 0.9, "remote_needed": false}'
    c = parse_classification(raw)
    assert (c.agent, c.confidence, c.remote_needed) == ("demo-agent", 0.9, False)

def test_parse_embedded():
    raw = 'Hier ist das Ergebnis: {"agent": "demo-agent", "confidence": 0.7, "remote_needed": true} hoffentlich'
    c = parse_classification(raw)
    assert c.remote_needed is True and c.agent == "demo-agent"

def test_parse_garbage_falls_back_to_remote():
    c = parse_classification("keine json hier")
    assert c.remote_needed is True and c.agent == "unknown" and c.confidence == 0.0

def test_classifier_with_mocked_ollama(monkeypatch):
    def fake_chat(model, messages):
        return {"message": {"content": '{"agent": "demo-agent", "confidence": 0.8, "remote_needed": false}'}}
    import ollama
    monkeypatch.setattr(ollama, "chat", fake_chat)
    c = OllamaClassifier("test-model").classify("Hallo", ["demo-agent"])
    assert c.agent == "demo-agent" and c.remote_needed is False
```

- [ ] **Step 2: Fehlschlag verifizieren** → `pytest tests/test_classify.py -v` (FAIL)

- [ ] **Step 3: Implementieren** `src/max/router/classify.py`

```python
import json
import re
from dataclasses import dataclass


@dataclass
class Classification:
    agent: str
    confidence: float
    remote_needed: bool


SYSTEM_PROMPT = (
    "Klassifiziere die Anfrage. Antworte NUR mit JSON im Format "
    '{"agent": <name>, "confidence": <Zahl 0-1>, "remote_needed": <true|false>}. '
    "Verfügbare lokale Agenten: {agents}"
)


def parse_classification(raw: str) -> Classification:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return Classification("unknown", 0.0, True)
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return Classification("unknown", 0.0, True)
    return Classification(
        str(data.get("agent", "unknown")),
        float(data.get("confidence", 0.0)),
        bool(data.get("remote_needed", False)),
    )


class OllamaClassifier:
    def __init__(self, model: str):
        self.model = model

    def classify(self, text: str, agents: list[str]) -> Classification:
        import ollama
        prompt = SYSTEM_PROMPT.format(", ".join(agents)) + f"\n\nAnfrage: {text}"
        resp = ollama.chat(model=self.model, messages=[{"role": "user", "content": prompt}])
        return parse_classification(resp["message"]["content"])
```

- [ ] **Step 4: Verifizieren + Commit** → `pytest tests/test_classify.py -v`, dann `git add max/ && git commit -m "max: ollama classifier with structured output"`

### Task 7: Agent-Registry + Demo-Agent

**Files:**
- Create: `src/max/agents/demo_agent.py`, `src/max/agents/registry.py`, `tests/test_agents.py`

- [ ] **Step 1: Failing Tests** `tests/test_agents.py`

```python
from max.agents.demo_agent import DemoAgent
from max.agents.registry import build_agents

def test_demo_agent_run():
    assert DemoAgent().run("Testfrage") == "Demo-Antwort zu: Testfrage"

def test_build_agents():
    profiles = [{"name": "demo-agent", "keywords": []}]
    agents = build_agents(profiles)
    assert "demo-agent" in agents
    assert isinstance(agents["demo-agent"], DemoAgent)

def test_build_agents_unknown_name_skipped():
    agents = build_agents([{"name": "unknown-agent"}])
    assert agents == {}
```

- [ ] **Step 2: Fehlschlag verifizieren** → `pytest tests/test_agents.py -v` (FAIL)

- [ ] **Step 3: Implementieren**

`src/max/agents/demo_agent.py`:
```python
class DemoAgent:
    name = "demo-agent"

    def run(self, query: str) -> str:
        return f"Demo-Antwort zu: {query}"
```

`src/max/agents/registry.py`:
```python
from max.agents.demo_agent import DemoAgent


def build_agents(profiles: list[dict]) -> dict[str, DemoAgent]:
    agents = {}
    for p in profiles:
        if p.get("name") == "demo-agent":
            agents[p["name"]] = DemoAgent()
    return agents
```

- [ ] **Step 4: Verifizieren + Commit** → `pytest tests/test_agents.py -v`, dann `git add max/ && git commit -m "max: agent registry + demo agent"`

### Task 8: TTS (Kokoro, Chunk-Streaming)

**Files:**
- Create: `src/max/tts/kokoro_tts.py`, `tests/test_tts.py`

- [ ] **Step 1: Failing Tests** `tests/test_tts.py`

```python
from max.tts.kokoro_tts import chunk_text, KokoroTts

def test_chunk_text_short():
    assert chunk_text("Hallo Welt.", max_chars=100) == ["Hallo Welt."]

def test_chunk_text_splits_long():
    text = ("Satz eins. " * 30)
    chunks = chunk_text(text, max_chars=100)
    assert all(len(c) <= 100 for c in chunks)
    assert len(chunks) > 1

def test_kokoro_tts_with_fake_k(monkeypatch):
    class FakeK:
        def generate(self, text):
            return (b"fake-audio", 22050)
    tts = KokoroTts()
    monkeypatch.setattr(KokoroTts, "_ensure", lambda self: FakeK())
    out = tts.synthesize_chunks("Hallo Welt. Bye.")
    assert out == [b"fake-audio", b"fake-audio"]
```

- [ ] **Step 2: Fehlschlag verifizieren** → `pytest tests/test_tts.py -v` (FAIL)

- [ ] **Step 3: Implementieren** `src/max/tts/kokoro_tts.py`

```python
import re


def chunk_text(text: str, max_chars: int = 200) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for s in sentences:
        if current and len(current) + len(s) + 1 > max_chars:
            chunks.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        chunks.append(current)
    return chunks


class KokoroTts:
    def __init__(self, voice: str = "af_de-1"):
        self.voice = voice
        self._k = None

    def _ensure(self):
        if self._k is None:
            from kokoro import K
            self._k = K(self.voice)
        return self._k

    def synthesize_chunks(self, text: str) -> list[bytes]:
        k = self._ensure()
        out = []
        for chunk in chunk_text(text):
            audio, _ = k.generate(chunk)
            out.append(audio.tobytes())
        return out
```

- [ ] **Step 4: Verifizieren + Commit** → `pytest tests/test_tts.py -v`, dann `git add max/ && git commit -m "max: Kokoro TTS with chunk streaming"`

### Task 9: Server-2-Stub (Mock Wake + Mock Antwort)

**Files:**
- Create: `src/max/remote/server2.py`, `tests/test_remote.py`

- [ ] **Step 1: Failing Tests** `tests/test_remote.py`

```python
from max.remote.server2 import MockServer2

def test_wake_returns_true():
    assert MockServer2().wake() is True

def test_ask_returns_answer():
    assert MockServer2().ask("Pong") == "[Großes Modell] Antwort zu: Pong"
```

- [ ] **Step 2: Fehlschlag verifizieren** → `pytest tests/test_remote.py -v` (FAIL)

- [ ] **Step 3: Implementieren** `src/max/remote/server2.py`

```python
class MockServer2:
    """Stub für Server 2: simuliert Wake-Trigger und Antwort des großen Modells."""

    def wake(self) -> bool:
        return True

    def ask(self, query: str) -> str:
        return f"[Großes Modell] Antwort zu: {query}"
```

- [ ] **Step 4: Verifizieren + Commit** → `pytest tests/test_remote.py -v`, dann `git add max/ && git commit -m "max: server2 mock stub"`

### Task 10: LangGraph-Router (State-Machine)

**Files:**
- Create: `src/max/router/graph.py`, `tests/conftest.py`, `tests/test_graph.py`

- [ ] **Step 1: Fakes anlegen** `tests/conftest.py`

```python
from max.router.classify import Classification


class FakeTranscriber:
    def transcribe(self, audio: bytes) -> str:
        return "Testfrage"


class FakeDiarizer:
    def diarize(self, audio: bytes):
        return [("SPEAKER_00", 0.0, 1.0)]


class FakeClassifier:
    def __init__(self, agent="demo-agent", confidence=0.9, remote_needed=False):
        self.agent = agent
        self.confidence = confidence
        self.remote_needed = remote_needed

    def classify(self, text: str, agents: list[str]) -> Classification:
        return Classification(self.agent, self.confidence, self.remote_needed)
```

- [ ] **Step 2: Failing Tests** `tests/test_graph.py`

```python
from max.agents.demo_agent import DemoAgent
from max.remote.server2 import MockServer2
from max.router.graph import build_graph
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def _graph(classifier, agents=None, server2=None):
    agents = agents if agents is not None else {"demo-agent": DemoAgent()}
    registry = [{"name": "Alex"}]
    return build_graph(FakeTranscriber(), FakeDiarizer(), registry, classifier, agents,
                       server2 if server2 is not None else MockServer2())


def test_local_route():
    result = _graph(FakeClassifier()).invoke({"audio": b"xx"})
    assert result["route"] == "local"
    assert result["speaker"] == "Alex"
    assert result["answer"] == "Demo-Antwort zu: Testfrage"

def test_remote_route():
    result = _graph(FakeClassifier(remote_needed=True)).invoke({"audio": b"xx"})
    assert result["route"] == "remote"
    assert result["answer"].startswith("Ich schalte den Hauptrechner ein.")

def test_low_confidence_goes_remote():
    assert _graph(FakeClassifier(confidence=0.2)).invoke({"audio": b"xx"})["route"] == "remote"

def test_unknown_agent_goes_remote():
    assert _graph(FakeClassifier(agent="unbekannt")).invoke({"audio": b"xx"})["route"] == "remote"

def test_classifier_failure_goes_remote():
    class Broken:
        def classify(self, text, agents):
            raise RuntimeError("ollama down")
    assert _graph(Broken()).invoke({"audio": b"xx"})["route"] == "remote"
```

- [ ] **Step 3: Fehlschlag verifizieren** → `pytest tests/test_graph.py -v` (FAIL: graph.py fehlt)

- [ ] **Step 4: Implementieren** `src/max/router/graph.py`

```python
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from max.config import resolve_speaker
from max.router.classify import Classification


class State(TypedDict):
    audio: bytes
    text: str
    speaker: str
    agent: str
    confidence: float
    remote_needed: bool
    route: str
    answer: str


def build_graph(transcriber, diarizer, registry, classifier, agents, server2):
    def transcribe(state):
        text = transcriber.transcribe(state["audio"])
        segments = diarizer.diarize(state["audio"])
        speaker = resolve_speaker([s[0] for s in segments], registry)
        return {"text": text, "speaker": speaker}

    def classify(state):
        try:
            c = classifier.classify(state["text"], list(agents.keys()))
        except Exception:
            c = Classification("unknown", 0.0, True)
        return {"agent": c.agent, "confidence": c.confidence, "remote_needed": c.remote_needed}

    def route(state):
        if state["remote_needed"] or state["agent"] not in agents or state["confidence"] < 0.5:
            return {"route": "remote"}
        return {"route": "local"}

    def respond_local(state):
        return {"answer": agents[state["agent"]].run(state["text"])}

    def respond_remote(state):
        server2.wake()
        return {"answer": f"Ich schalte den Hauptrechner ein. {server2.ask(state['text'])}"}

    g = StateGraph(State)
    g.add_node("transcribe", transcribe)
    g.add_node("classify", classify)
    g.add_node("route", route)
    g.add_node("respond_local", respond_local)
    g.add_node("respond_remote", respond_remote)
    g.add_edge(START, "transcribe")
    g.add_edge("transcribe", "classify")
    g.add_edge("classify", "route")
    g.add_conditional_edges("route",
                            lambda s: "respond_local" if s["route"] == "local" else "respond_remote")
    g.add_edge("respond_local", END)
    g.add_edge("respond_remote", END)
    return g.compile()
```

- [ ] **Step 5: Verifizieren + Commit** → `pytest tests/test_graph.py -v` (alle 5 PASS), dann `git add max/ && git commit -m "max: langgraph router state machine"`

### Task 11: main.py (Wiring: Mic → Pipeline → TTS)

**Files:**
- Create: `src/max/main.py`

- [ ] **Step 1: Implementieren** `src/max/main.py`

```python
import os
import sounddevice as sd
import numpy as np

from max.agents.registry import build_agents
from max.config import load_agent_profiles, load_speakers
from max.pipeline.diarization import PyannoteDiarizer
from max.pipeline.stt import WhisperTranscriber
from max.pipeline.vad import SAMPLE_RATE, frame_bytes, Vad
from max.remote.server2 import MockServer2
from max.router.classify import OllamaClassifier
from max.router.graph import build_graph
from max.tts.kokoro_tts import KokoroTts


def capture_audio(vad: Vad, max_seconds: float = 30.0, end_silence_frames: int = 5):
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


def main():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    registry = load_speakers(os.path.join(root, "config", "speakers.yaml"))
    agents = build_agents(load_agent_profiles(os.path.join(root, "config", "agents")))
    graph = build_graph(
        WhisperTranscriber(),
        PyannoteDiarizer(),
        registry,
        OllamaClassifier(os.environ.get("MAX_OLLAMA_MODEL", "qwen2.5:9b")),
        agents,
        MockServer2(),
    )
    vad = Vad()
    tts = KokoroTts()
    while True:
        audio = capture_audio(vad)
        if audio is None:
            continue
        result = graph.invoke({"audio": audio})
        print(f"[Max] ({result['speaker']}): {result['answer']}")
        for chunk in tts.synthesize_chunks(result["answer"]):
            sd.play(np.frombuffer(chunk, dtype=np.int16), 22050)
            sd.wait()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax-Check** → `.venv/bin/python -m py_compile src/max/main.py` (kein Fehler; Mic wird NICHT gestartet)
- [ ] **Step 3: Commit** → `git add max/ && git commit -m "max: main wiring (mic → pipeline → tts)"`

### Task 12: E2E-Smoke-Test (vollständiger Loop mit Fakes)

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Test schreiben**

```python
from max.agents.demo_agent import DemoAgent
from max.remote.server2 import MockServer2
from max.router.graph import build_graph
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def test_e2e_local_flow():
    agents = {"demo-agent": DemoAgent()}
    g = build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                    FakeClassifier(), agents, MockServer2())
    result = g.invoke({"audio": b"synthetic-audio"})
    assert result["speaker"] == "Alex"
    assert result["route"] == "local"
    assert result["answer"] == "Demo-Antwort zu: Testfrage"


def test_e2e_remote_flow():
    agents = {"demo-agent": DemoAgent()}
    g = build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                    FakeClassifier(remote_needed=True), agents, MockServer2())
    result = g.invoke({"audio": b"synthetic-audio"})
    assert result["route"] == "remote"
    assert "[Großes Modell]" in result["answer"]
```

- [ ] **Step 2: Verifizieren + Commit** → `pytest tests/test_e2e.py -v` (2 PASS), dann `git add max/ && git commit -m "max: e2e smoke test"`

### Task 13: Vollständige Verifikation

- [ ] **Step 1: Gesamte Test-Suite laufen lassen**

```
cd /home/user/max && .venv/bin/python -m pytest -v
```
Expected: alle Tests PASS (keine GPU/Mic/Netzwerk nötig).

- [ ] **Step 2: Import-Smoke-Check**

```
cd /home/user/max && .venv/bin/python -c "import max.main"
```
Expected: kein Fehler (keine Modell-Downloads bei Import).

- [ ] **Step 3: Finaler Commit**

```
git add max/ && git commit -m "max: walking skeleton complete (subprojekt A)"
```
