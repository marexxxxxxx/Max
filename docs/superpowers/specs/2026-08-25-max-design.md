# Max — Lokales Sprachassistenz-System (Design-Doc)

- **Datum:** 2026-08-25
- **Status:** Design vom Nutzer bestätigt (Walking Skeleton = Subprojekt A)
- **Repo:** `/home/user/max`

## 1. Zweck

Lokales, modulares Sprachassistenz-System („Jarvis"-Prinzip): Spracheingabe → lokales Routing über ein kleines KI-Modell → Fach-Agenten → Streaming-TTS-Antwort. Komplexere Aufgaben werden an ein größeres KI-Modell auf einem separaten Rechner ausgelagert.

## 2. Systemarchitektur (2 Server)

| | Server 1 (Low-Machine) | Server 2 (High-Machine, remote) |
|---|---|---|
| Zustand | Immer an | On-demand, wachgerufen |
| STT + Speaker-Recognition | ✔ (faster-whisper + pyannote-audio) | — |
| KI-Modell | Klein: quantisiertes Qwen 3.5 9B via **ollama** | Groß: (Modell frei wählbar, konfigurierbar) |
| Agenten | Einfache lokale Agenten | — |
| TTS | ✔ (Kokoro, Deutsch) | — |
| Rolle | Nimmt Anfrage entgegen, versuch lokal lösen | Löst nur, wenn Server 1 scheitert |

- **Orchestrierung:** LangGraph auf Server 1. Entscheidung: lokaler Agent vs. Remote-Server 2.
- **Server-Kommunikation:** HTTP über LAN (Server 1 → Server 2, Antwort zurück).
- **Wake-Trigger Server 2:** im Skeleton per Mock (WLAN-Signal-Trigger); später Hardware-Modul am Mainboard.

## 3. Walking Skeleton (Subprojekt A) — Komponenten

### 3.1 Voice-Pipeline
- Mikrofon-Erfassung mit **VAD** (Voice Activity Detection), z. B. webrtc-vad
- **faster-whisper** für Transkription (Deutsch + Englisch)
- **pyannote-audio** für Speaker-Diarization — **Speaker-Recognition aktiv ab Start**: Output enthält `text` und `speaker`
- Bekannte Sprecher via konfigurierbare Speaker-Registry (YAML)

### 3.2 Router (LangGraph)
State-Machine:
```
idle → listening → transcribe → classify → (route_local | route_remote) → respond → tts → idle
```
- **Klassifikation:** kleines 9B-Modell (ollama) mit strukturiertem Output:
  `{agent: <name>, confidence: <float>, remote_needed: <bool>}`
- **Routing-Entscheidung:**
  - `remote_needed=true` oder kein passender lokaler Agent → Fallback-Logik:
    Sprachmeldung „Ich schalte den Hauptrechner ein" + Wake-Trigger an Server 2
  - sonst → zuständiger lokaler Agent

### 3.3 Agenten
- Skeleton: **1 Mock-Agent** („Demo-Agent") mit trivialer, testbarer Funktion (z. B. festes Antworttemplate / einfache Echo-Antwort).
- Deklarative Agenten-Profile als YAML (Grundgerüst für Subprojekt B):
  ```yaml
  name: demo-agent
  description: ...
  keywords: [...]
  capabilities: [...]
  ```
- OpenCode-Instanzen als Fach-Agenten kommen in Subprojekt B (isolierte Instanzen, eigene System-Prompts, MCP-Server, Human-in-the-Loop für autonome Starts).

### 3.4 TTS
- **Kokoro** (Deutsch, natürliche Qualität)
- **Streaming:** Text in Chunk aufgeteilt, Audio-Segmente parallel zur Token-Generierung abgespielt (minimale Latenz)

### 3.5 Server 2 (Stub im Skeleton)
- Mock: Trigger → simulierter „Start" (verzögert, logbar) → simulierte Antwort des großen Modells
- Kein echtes Modell im Skeleton; echte Anbindung kommt in Subprojekt E

## 4. Datenfluss (End-to-End)

```
Mic → VAD → faster-whisper (text) + pyannote (speaker)
  → LangGraph: classify (ollama 9B)
  → route_local: Agent antwortet (Text-Stream)
  → route_remote: „Hauptrechner"-Meldung + Wake-Stub → Antwort
  → Kokoro Chunk-Streaming → Lautsprecher
```

## 5. Fehlerbehandlung

| Fehler | Verhalten |
|---|---|
| Kein Spracheingabe / VAD triggert | System bleibt idle |
| STT/Speaker-Fehler | Fehlermeldung per TTS, zurück zu idle |
| ollama nicht verfügbar | Fallback: direkt „Hauptrechner"-Routierung |
| Server 2 nicht erreichbar / Timeout | TTS: „Der Hauptrechner ist nicht erreichbar", zurück zu idle |
| Agent stirbt mid-response | Stream abbrechen, TTS-Fehlermeldung |

## 6. Tests

- **Unit:** VAD/STT (synthetische Test-Audio), Router-Entscheidung (mockte ollama-Responses), Kokoro-Chunking
- **Integration:** vollständiger Loop mit Test-Audio-Datei
- **E2E-Smoke:** Sprachbefehl → Routing → Mock-Agent → TTS-Antwort

## 7. Projektstruktur (Vorschlag)

```
/home/user/max/
├── docs/superpowers/specs/
├── config/
│   └── agents/            # YAML-Profile
├── src/max/
│   ├── pipeline/          # VAD, STT, Speaker-Registry
│   ├── router/            # LangGraph-Graph
│   ├── agents/            # Agent-Implementierungen
│   ├── tts/               # Kokoro Streaming
│   └── remote/            # Server-2-Client + Mock
└── tests/
```

## 8. Roadmap (Subprojekte, in Reihenfolge)

| # | Subprojekt | Scope |
|---|---|---|
| **A** | Walking Skeleton | Voice → Router → 1 Mock-Agent → TTS; Server 2 als Stub |
| B | Agenten-Plattform | YAML-Profile, OpenCode-Instanzen, MCP, Human-in-the-Loop |
| C | Smart Mirror / Display | Display-Templates, Agenten pushen visuelle Daten |
| D | Web-Dashboard + Telemetrie | Live-Tracking, SQL-DB (Tokens, Latenzen), Agent-Administration |
| E | Remote-PC (echt) | Echtes Wake (WLAN/Hardware), Anbindung des großen Modells |

Jedes Subprojekt: eigene Spec → eigener Plan → Implementierung.

## 9. Annahmen & offene Punkte

- Großes Modell auf Server 2: bewusst nicht fixiert — konfigurierbar (freie Wahl des Nutzers)
- Sprecher-Registry: Anzahl/namen der bekannten Sprecher konfigurierbar
- Low-Machine-Spezifikationen: nicht bekannt → pyannote-audio läuft CPU-fähig; bei zu langsamer Erkennung später Optimierungen (z. B. kleinere Modelle)
- Sprache: primär Deutsch
