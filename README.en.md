# Max — Local Voice Assistant

> [🇩🇪 German](README.md) · [🇬🇧 English](README.en.md)

**Max** is a fully local, voice-driven assistant. It connects microphone capture, speech-to-text,
speaker diarization, AI routing, specialist agents (opencode) and text-to-speech (Piper) in one
closed loop. Max runs entirely locally (Ollama + opencode) and can wake up a separate machine
(**Server 2**) running a large model when needed.

## Table of Contents

1. [Architecture](#1-architecture)
   - [Components](#components)
   - [Routing Logic](#routing-logic)
   - [Two Machines](#two-machines)
2. [Installation](#2-installation)
   - [Docker (recommended)](#docker-recommended)
   - [Native (uv)](#native-uv)
   - [Configuration](#configuration)
3. [Usage](#3-usage)

## 1. Architecture

Max is built as a **LangGraph state machine**. Each request follows this flow:

```
Microphone (VAD)
   → STT (faster-whisper)
   → Diarization (pyannote) → speaker
   → Classification (Ollama qwen3.5:9b)
   → Routing (LangGraph)
        ├─ local      → specialist agent (opencode)
        ├─ remote     → HITL gate → Server 2
        └─ interview  → onboarding
   → answer (TTS: Piper) + telemetry
```

### Components

| Component | Module | Role |
|---|---|---|
| Audio capture | `src/max/pipeline/vad.py` | VAD detects speech; `capture_audio` records up to 30 s |
| Speech recognition | `src/max/pipeline/stt.py` | faster-whisper transcribes audio → text |
| Diarization | `src/max/pipeline/diarization.py` | pyannote detects the speaker; `resolve_speaker` maps it |
| Routing | `src/max/router/graph.py` | LangGraph state machine: transcription → classification → routing |
| Classifier | `src/max/router/classify.py` | Ollama (`qwen3.5:9b`) classifies: agent + confidence + `remote_needed` |
| Specialist agents | `src/max/agents/runner.py` | `OpencodeRunner` runs opencode agents over HTTP/SSE |
| HITL gate | `src/max/router/hitl.py` | remote routing requires a spoken confirmation from the user |
| Text-to-speech | `src/max/tts/piper_tts.py` | Piper (`de_DE-thorsten-medium`) speaks the answers |
| Remote service | `src/max/remote/service.py` | Server 2: large model, endpoints `/health`, `/wake`, `/ask` |
| Remote client | `src/max/remote/client.py` | wakes Server 2 (HTTP / power switch) and asks |
| Display | `src/max/display/server.py` | Smart Mirror (clock, weather, calendar, agent cards) via SSE |
| Dashboard | `src/max/dashboard/server.py` | telemetry + agent admin |
| Telemetry | `src/max/telemetry/` | latency + token counts per stage (SQLite) |
| Person profile | `src/max/agents/person.py` | shared profile (`person.yaml`), injected into agent prompts |

### Routing Logic

In `router/graph.py`:

- `onboarding` → interview node
- `remote_needed` **or** unknown agent **or** confidence < 0.5 → HITL gate (`respond_remote`)
- known agent + high confidence → local (specialist agent)
- `[ESCALATE]` from an agent → HITL gate
- interview mode: `[ASK]` keeps the conversation going, `[DONE]` ends it (max 10 turns)

### Two Machines

- **Server 1 (small):** full pipeline — microphone, STT, diarization, routing, agents, TTS,
  display, dashboard. Local Ollama models: `qwen3.5:9b` (classifier) and `max-9b`
  (opencode reasoning).
- **Server 2 (big):** only the remote service with the large model (Ollama); woken up on demand.

## 2. Installation

### Docker (recommended)

The `max-voice-assistant:latest` image bundles opencode, ollama, the Piper voice and
faster-whisper. The Ollama models (`max-9b`, `qwen3.5:9b`) are **custom** and not in the public
registry — they must be provided via a volume.

```bash
# 1. Put the Ollama models into the volume
docker volume create ollama-models
# copy the contents of ~/.ollama/models/* into the volume (or import GGUF files)

# 2. Start it
docker compose up -d
```

For real audio you must provide host audio passthrough (e.g. `--device /dev/snd` or a PulseAudio
socket). Details: [`docs/docker.md`](docs/docker.md).

### Native (uv)

```bash
# Install dependencies (Python >= 3.12)
uv sync --extra-dev

# The pyannote model is gated and needs a HuggingFace token
export HF_TOKEN="<your_token>"

# Classifier model
ollama pull qwen3.5:9b
ollama serve   # port 11434

# Put the Piper voice into data/voices/
python -m piper.download_voices de_DE-thorsten-medium --download-dir data/voices

# opencode must be in the PATH
uv run python -m max.main --serve-display --serve-dashboard
```

Requirements: PortAudio (`sudo apt install portaudio19-dev`) and optionally network access to
Server 2. Details: [`docs/installation.md`](docs/installation.md).

### Configuration

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `MAX_OLLAMA_MODEL` | `qwen3.5:9b` | classifier model |
| `MAX_REMOTE_HOST` | — | Server 2 host; empty → MockServer2 |
| `MAX_REMOTE_PORT` | `8090` | remote service port |
| `MAX_REMOTE_BACKEND` | `ollama` | `ollama` / `http` / `stub` (Server 2) |
| `MAX_REMOTE_MODEL` | `llama3` | model for the remote ask |
| `MAX_POWER_SWITCH_CMD` | — | command to power on Server 2 |
| `MAX_DISPLAY_PORT` | `8080` | display (Smart Mirror) |
| `MAX_DASHBOARD_PORT` | `8081` | dashboard |

## 3. Usage

**Start:**

```bash
# native
uv run python -m max.main --serve-display --serve-dashboard
# or via Docker
docker compose up -d
```

**VAD loop flow:**

1. **Speak:** Max waits in the VAD loop. Once you speak, it records up to 30 s.
2. **Understand:** The audio is transcribed, the speaker is identified and the request classified.
3. **Answer:** Max responds by speech (Piper). Known specialist agents (e.g. the nutrition planner)
   run locally. Uncertain or complex requests require a spoken confirmation — then Server 2 is
   woken up.
4. **Onboarding:** Say something like *"let's get to know each other"* → Max runs an interview and
   fills in the shared person profile.
5. **Display:** Smart Mirror at `http://localhost:8080` (clock, weather, calendar, agent cards).
6. **Dashboard:** telemetry + agent admin at `http://localhost:8081`.

**Smoke test (no microphone):**

```bash
uv run python scripts/system_test.py --mock
```
