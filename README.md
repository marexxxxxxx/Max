# Max — Lokaler Sprachassistent

> [🇩🇪 Deutsch](README.md) · [🇬🇧 English](README.en.md)

**Max** ist ein lokal laufender, sprachgesteuerter Assistent. Er verbindet Mikrofon-Aufnahme,
Spracherkennung, Diarization, KI-Routing, Fach-Agenten (opencode) und Text-zu-Sprache (Piper)
in einem geschlossenen Kreis. Max läuft vollständig lokal (Ollama + opencode) und kann bei
Bedarf einen separaten Rechner (**Server 2**) mit einem großen Modell wachrufen.

## Inhaltsverzeichnis

1. [Aufbau (Architecture)](#1-aufbau-architecture)
   - [Komponenten](#komponenten)
   - [Routing-Logik](#routing-logik)
   - [Zwei Maschinen](#zwei-maschinen)
2. [Installation](#2-installation)
   - [Docker (empfohlen)](#docker-empfohlen)
   - [Nativ (uv)](#nativ-uv)
   - [Konfiguration](#konfiguration)
3. [Nutzung (Usage)](#3-nutzung-usage)

## 1. Aufbau (Architecture)

Max ist als **LangGraph-State-Machine** aufgebaut. Pro Anfrage läuft der folgende Ablauf:

```
Mikrofon (VAD)
   → STT (faster-whisper)
   → Diarization (pyannote) → Sprecher
   → Klassifikation (Ollama qwen3.5:9b)
   → Routing (LangGraph)
        ├─ lokal      → Fach-Agent (opencode)
        ├─ remote     → HITL-Gate → Server 2
        └─ interview  → Onboarding
   → Antwort (TTS: Piper) + Telemetrie
```

### Komponenten

| Komponente | Modul | Aufgabe |
|---|---|---|
| Audio-Erfassung | `src/max/pipeline/vad.py` | VAD erkennt Sprache, `capture_audio` nimmt max. 30 s auf |
| Spracherkennung | `src/max/pipeline/stt.py` | faster-whisper transkribiert Audio → Text |
| Diarization | `src/max/pipeline/diarization.py` | pyannote erkennt den Sprecher, `resolve_speaker` ordnet ihn zu |
| Routing | `src/max/router/graph.py` | LangGraph-State-Machine: Transkription → Klassifikation → Routing |
| Klassifikator | `src/max/router/classify.py` | Ollama (`qwen3.5:9b`) klassifiziert: Agent + Konfidenz + `remote_needed` |
| Fach-Agenten | `src/max/agents/runner.py` | `OpencodeRunner` führt opencode-Agenten über HTTP/SSE aus |
| HITL-Gate | `src/max/router/hitl.py` | Remote-Routing braucht eine Sprachbestätigung des Users |
| Text-zu-Sprache | `src/max/tts/piper_tts.py` | Piper (`de_DE-thorsten-medium`) spricht die Antworten |
| Remote-Service | `src/max/remote/service.py` | Server 2: großes Modell, Endpunkte `/health`, `/wake`, `/ask` |
| Remote-Client | `src/max/remote/client.py` | weckt Server 2 (HTTP/Power-Switch) und fragt |
| Display | `src/max/display/server.py` | Smart Mirror (Uhr, Wetter, Kalender, Agent-Cards) via SSE |
| Dashboard | `src/max/dashboard/server.py` | Telemetrie + Agent-Admin |
| Telemetrie | `src/max/telemetry/` | Latenz + Token-Zählung pro Stufe (SQLite) |
| Personen-Profil | `src/max/agents/person.py` | Gemeinsames Profil (`person.yaml`), in Agent-Prompts injiziert |

### Routing-Logik

In `router/graph.py`:

- `onboarding` → Interview-Node
- `remote_needed` **oder** unbekannter Agent **oder** Konfidenz < 0.5 → HITL-Gate (`respond_remote`)
- bekannter Agent + hohe Konfidenz → lokal (Fach-Agent)
- `[ESCALATE]` von einem Agent → HITL-Gate
- Interview-Modus: `[ASK]` hält das Gespräch, `[DONE]` beendet es (max. 10 Turns)

### Zwei Maschinen

- **Server 1 (klein):** komplette Pipeline — Mikrofon, STT, Diarization, Routing, Agenten, TTS,
  Display, Dashboard. Lokale Ollama-Modelle: `qwen3.5:9b` (Klassifikator) und `max-9b`
  (opencode-Reasoning).
- **Server 2 (groß):** nur der Remote-Service mit dem großen Modell (Ollama); wird bei Bedarf
  wachgerufen.

## 2. Installation

### Docker (empfohlen)

Das Image `max-voice-assistant:latest` bündelt opencode, ollama, Piper-Voice und faster-whisper.
Die Ollama-Modelle (`max-9b`, `qwen3.5:9b`) sind **Custom** und nicht im Public-Registry —
sie müssen über ein Volume bereitgestellt werden.

```bash
# 1. Ollama-Modelle ins Volume legen
docker volume create ollama-models
# Inhalte von ~/.ollama/models/* in das Volume kopieren (oder GGUF-Dateien importieren)

# 2. Starten
docker compose up -d
```

Für echte Audio muss der Host-Audio bereitgestellt werden (z. B. `--device /dev/snd` oder ein
PulseAudio-Socket). Details: [`docs/docker.md`](docs/docker.md).

### Nativ (uv)

```bash
# Dependencies installieren (Python >= 3.12)
uv sync --extra-dev

# Pyannote-Modell (gated) braucht einen HuggingFace-Token
export HF_TOKEN="<dein_token>"

# Klassifikator-Modell
ollama pull qwen3.5:9b
ollama serve   # Port 11434

# Piper-Voice in data/voices/ legen
python -m piper.download_voices de_DE-thorsten-medium --download-dir data/voices

# opencode muss im PATH sein
uv run python -m max.main --serve-display --serve-dashboard
```

Voraussetzungen: PortAudio (`sudo apt install portaudio19-dev`) und optional Netzwerk-Access zu
Server 2. Details: [`docs/installation.md`](docs/installation.md).

### Konfiguration

Umgebungsvariablen:

| Variable | Standard | Wirkung |
|---|---|---|
| `MAX_OLLAMA_MODEL` | `qwen3.5:9b` | Klassifikator-Modell |
| `MAX_REMOTE_HOST` | — | Host von Server 2; leer → MockServer2 |
| `MAX_REMOTE_PORT` | `8090` | Port des Remote-Service |
| `MAX_REMOTE_BACKEND` | `ollama` | `ollama` / `http` / `stub` (Server 2) |
| `MAX_REMOTE_MODEL` | `llama3` | Modell für den Remote-Ask |
| `MAX_POWER_SWITCH_CMD` | — | Befehl zum Einschalten von Server 2 |
| `MAX_DISPLAY_PORT` | `8080` | Display (Smart Mirror) |
| `MAX_DASHBOARD_PORT` | `8081` | Dashboard |

## 3. Nutzung (Usage)

**Start:**

```bash
# nativ
uv run python -m max.main --serve-display --serve-dashboard
# oder via Docker
docker compose up -d
```

**Ablauf im VAD-Loop:**

1. **Sprechen:** Max wartet im VAD-Loop. Sobald du sprichst, nimmt er bis zu 30 s auf.
2. **Verstehen:** Das Audio wird transkribiert, der Sprecher erkannt und die Anfrage klassifiziert.
3. **Antwort:** Max antwortet per Sprache (Piper). Bekannte Fach-Agenten (z. B. Ernährungsplaner)
   werden lokal ausgeführt. Unsichere oder komplexe Anfragen erfordigen eine Sprachbestätigung —
   dann wird Server 2 wachgerufen.
4. **Onboarding:** Sag etwas wie *„lass uns kennenlernen“* → Max führt ein Interview und befüllt
   das gemeinsame Personen-Profil.
5. **Display:** Smart Mirror unter `http://localhost:8080` (Uhr, Wetter, Kalender, Agent-Cards).
6. **Dashboard:** Telemetrie + Agent-Admin unter `http://localhost:8081`.

**Smoke-Test (ohne Mikrofon):**

```bash
uv run python scripts/system_test.py --mock
```
