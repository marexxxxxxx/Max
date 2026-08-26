# Max — Installations-Anleitung (zwei Maschinen)

Max läuft auf zwei Maschinen:
- **Server 1 (kleine Maschine):** Lokale Pipeline — Mikrofon, STT, Diarization,
  Routing, Fach-Agenten (opencode), TTS, Display, Dashboard.
- **Server 2 (große Maschine):** Nur der Remote-Service mit dem großen Modell
  (Ollama). Wird bei Bedarf wachgerufen.

Beide laufen am besten unter **uv** (Repo nutzt `pyproject.toml`, Python ≥ 3.12).

---

## 1. Server 1 — kleine Maschine (Max)

### 1.1 Voraussetzungen
- Linux mit Python ≥ 3.12
- Mikrofon + Lautsprecher (PortAudio). Installation:
  ```bash
  sudo apt install portaudio19-dev   # oder: apt install libportaudio2
  ```
- Netzwerk-Access zu Server 2 (LAN)

### 1.2 Projekt installieren
```bash
cd /home/user/max        # oder: repo klonen/ziehen
uv sync --extra-dev      # alle Dependencies inkl. pytest
```
Wichtige Dependencies (aus `pyproject.toml`):
- `faster-whisper` (STT), `pyannote.audio` (Diarization)
- `kokoro` (TTS), `langgraph` (Routing), `ollama` (Klassifikator)
- `sounddevice` (Mikrofon/Lautsprecher), `webrtcvad` (VAD)

### 1.3 Modelle vorheizen (einmalig)
- **Whisper:** lädt sich das Modell beim ersten Start selbst (Default `small`).
- **Pyannote:** `pyannote/speaker-diarization-3.0` — **braucht einen
  HuggingFace-Token** (Terms akzeptieren), da das Modell gated ist:
  ```bash
  export HF_TOKEN="<dein_token>"   # oder im ~/.config/huggingface/hf_token
  ```
- **Ollama (Klassifikator):** Model pullen:
  ```bash
  ollama pull qwen3.5:9b   # Default-Model, änderbar via MAX_OLLAMA_MODEL
  ```
  Ollama-Server muss laufen: `ollama serve` (Port 11434).

### 1.4 opencode CLI
Der Agent-Runner nutzt die opencode-CLI. Sie muss im PATH sein
(in dieser Umgebung: `/home/user/.opencode/bin/opencode`).

### 1.5 Start
```bash
uv run python -m max.main --serve-display --serve-dashboard
```
- Mikrofon-Loop startet (VAD-gesteuert).
- Display: http://localhost:8080 (Smart Mirror)
- Dashboard: http://localhost:8081 (Telemetrie + Agent-Admin)

### 1.6 Smoke-Test (ohne Mikrofon)
```bash
uv run python scripts/system_test.py --mock
# oder mit echtem Audio:
uv run python scripts/system_test.py --real --audio /pfad/zur.wav
```

### 1.7 Connection zu Server 2
Damit Max Server 2 aktiviert, muss `MAX_REMOTE_HOST` gesetzt sein:
```bash
export MAX_REMOTE_HOST=<ip-oder-hostname-server2>
# optional:
export MAX_REMOTE_PORT=8090
export MAX_REMOTE_TIMEOUT=60
export MAX_REMOTE_WAKE_TIMEOUT=120
export MAX_POWER_SWITCH_CMD="<Befehl zum Einschalten>"   # optional
```
Ohne `MAX_REMOTE_HOST` läuft Max mit `MockServer2` (Dev-Default).

---

## 2. Server 2 — große Maschine (Remote)

### 2.1 Voraussetzungen
- Python ≥ 3.12 (nur das Remote-Service-Modul nötig)
- Ollama mit dem großen Modell:
  ```bash
  ollama pull <großes-modell>   # z. B. llama3, 70b etc.
  ```

### 2.2 Start
```bash
uv sync                      # gleiche Dependencies (oder nur das Service-Modul)
export MAX_REMOTE_PORT=8090
export MAX_REMOTE_BACKEND=ollama
export MAX_REMOTE_MODEL=<modell>
export MAX_OLLAMA_HOST=127.0.0.1
export MAX_OLLAMA_PORT=11434
uv run python -m max.remote.service
```
Endpunkte (aus `remote/service.py`):
- `GET /health`
- `POST /wake`
- `POST /ask`

### 2.3 Firewall
Port 8090 muss von Server 1 erreichbar sein.

---

## 3. Konfiguration — was kann man konfigurieren?

### 3.1 Umgebungsvariablen
| Variable | Standard | Wirkung |
|---|---|---|
| `MAX_REMOTE_HOST` | — | Host von Server 2; leer → MockServer2 |
| `MAX_REMOTE_PORT` | 8090 | Port des Remote-Service |
| `MAX_REMOTE_TIMEOUT` | 60 | Ask-Timeout (s) |
| `MAX_REMOTE_WAKE_TIMEOUT` | 120 | Wake-Poll-Timeout (s) |
| `MAX_POWER_SWITCH_CMD` | — | Befehl zum Einschalten von Server 2 |
| `MAX_OLLAMA_MODEL` | qwen2.5:9b (main.py) / qwen3.5:9b (system_test) | Klassifikator-Modell |
| `MAX_REMOTE_BACKEND` | ollama | ollama / http / stub (Server 2) |
| `MAX_REMOTE_MODEL` | llama3 | Modell für den Remote-Ask |
| `MAX_REMOTE_MODEL_URL` | — | URL bei `http`-Backend |
| `MAX_OLLAMA_HOST` / `MAX_OLLAMA_PORT` | 127.0.0.1 / 11434 | Ollama auf Server 2 |
| `MAX_DISPLAY_PORT` | 8080 | Display-Server |
| `MAX_DASHBOARD_PORT` | 8081 | Dashboard |

### 3.2 Config-Dateien
- `config/speakers.yaml` — Sprecher-Registry (Namen für Diarization-Zuordnung)
- `config/agents/*.yaml` — Agent-Profile (name, description, keywords,
  capabilities, memory_dir, person_path)
- `config/opencode/opencode.json` — opencode-Agenten (prompt, permissions, MCP)
- `config/opencode/*.prompt.md` — System-Prompts der Agenten
- `config/calendar.json` — Kalender-Events (optional, für die Kalender-Card)
- `data/memory/person.yaml` — gemeinsames Personen-Profil (per Onboarding-Interview)
- `data/agents/<agent>/profile.yaml` + `memory.md` — Agent-Memory
- `data/display/cards/` — Agent-Cards (JSON)

### 3.3 Ports (Zusammenfassung)
| Dienst | Port |
|---|---|
| Display (Mirror) | 8080 |
| Dashboard | 8081 |
| Server-2-Service | 8090 |
| Ollama (Server 2) | 11434 |
| Ollama (Server 1, Klassifikator) | 11434 |

---

## 4. Start-Checkliste (einfach)
1. Server 2: Ollama + großes Modell, `python -m max.remote.service` starten.
2. Server 1: `uv sync`, HF-Token, Ollama + qwen3.5:9b, opencode im PATH.
3. Server 1: `MAX_REMOTE_HOST` setzen.
4. `uv run python scripts/system_test.py --mock` → muss `OK` liefern.
5. `uv run python -m max.main --serve-display --serve-dashboard`.
6. Dashboard auf `localhost:8081` prüfen.
