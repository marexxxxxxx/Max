# Max — Agenten-Plattform (Design-Doc, Subprojekt B)

- **Datum:** 2026-08-25
- **Status:** Design vom Nutzer bestätigt
- **Repo:** `/home/user/max`
- **Vorausgesetzt:** Subprojekt A (Walking Skeleton) ist umgesetzt

## 1. Zweck

Aus dem 1 Mock-Agent des Skeletons wird eine **Plattform**: generischer Agent-Runner mit pluggable Backends, auf dem **mehrere** Fach-Agenten als **eigene opencode-Agenten** laufen (eigene System-Prompts, eigene MCP-Server, eigene Memory). Der Ernährungsplaner mit Mealie-Anbindung ist das erste Beispiel; die Plattform ist von Grund auf für mehrere Agenten ausgelegt. Human-in-the-Loop (HITL) steuert alle Eskalationen an Server 2.

## 2. Kernentscheidungen (vom Nutzer bestätigt)

| Thema | Entscheidung |
|---|---|
| Ausführung | Generischer Agent-Runner mit pluggable Backends (kein Backend fest verdrahtet) |
| Agent-Konzept | Jeder Fachbereich = eigener opencode-Agent (System-Prompt + MCP-Servern); Eskalation nur mit Sprachbestätigung des Users |
| Scope B | Plattform für **mehrere Agents** + Ernährungsplaner als erstes Beispiel. Neue Agenten folgen per YAML + prompt.md + opencode.json-Eintrag, ohne Architektur-Änderung |
| HITL | Eskalation an größeren Agent (Server 2) braucht Sprachbestätigung; expliziter Sprachbefehl „erweiterten modus" leitet direkt dorthin; im B bleibt Server 2 der Mock |
| Memory | Dateibasierte Memory pro Agent (`profile.yaml` + `memory.md`) hinter einem Memory-Interface; Vector-Backend später nachrüstbar |
| Mealie | Selbst gehostet; MCP via offiziellem Community-Server (`rldiao/mealie-mcp-server`); reine opencode-Konfiguration, kein eigener Code |
| Eskalation | Zwei Pfade (Klassifikator + Agent-Selbst-Eskalation), ein gemeinsames HITL-Gate |
| Implementierungs-Stil | **Ausführliche Comments und Erklärungen im Code** (globales Constraint) |

## 3. Architektur

```
Mic → VAD → STT + Diarization → Klassifikator (ollama)
        → route_local:  Agent-Runner (opencode-Agent + Memory) → Antwort
        → route_remote: HITL-Gate (Sprachbestätigung) → MockServer2
        → TTS (Kokoro, Chunk-Streaming)
```

Neuer Graph-Zweig gegenüber A: `route_local` führt zu einem `agent_run`-Node, der den Agent-Runner aufruft (statt Demo-Agent); `route_remote` führt zu einem `hitl`-Node mit Sprachbestätigung, dann MockServer2.

### 3.1 Agent-Runner

- **Interface:** `AgentRunner.run(agent_config: AgentProfile, task: str) -> AgentResult`
  - `AgentResult`: `answer: str`, `escalated: bool`, `escalation_reason: str | None`
- **Backends:**
  - `OpencodeSubprocessBackend` (Produktion): startet opencode nicht-interaktiv (`opencode run --agent <name>` mit Task-Prompt, der die Memory-Context enthält), parst die Antwort. Erkennt den strukturierten Marker `[ESCALATE] <reason>` im Agent-Output → `escalated=True`.
  - `MockAgentBackend` (Tests): deterministische Antworten, inkl. Simulierung von Eskalation und Memory-Writes; keine echten opencode-Launches.
- **Backend-Auswahl:** konfigurierbar (`runner`-Feld im Agent-Profil, Default `opencode`); Tests inyectieren `mock`.
- **Timeout & Fehler:** Runner hat Timeout; bei Crash/Timeout → `answer = Fehlermeldung`, zurück in den Graph-Flow (TTS-Fehlermeldung), kein Absturz des ganzen Systems.

### 3.2 Agent-Profile (YAML)

```yaml
# config/agents/<name>.yaml
name: ernährungsplaner
description: Ernährungs- und Ernährungsplan-Experte
keywords: [ernährung, essen, protein, rezepte, plan, fitness]
capabilities: [meal plans, recipes, nutrition planning]
runner: opencode            # opencode | mock
mcp_servers: [mealie]       # aus opencode.json
memory: data/agents/ernährungsplaner
system_prompt: config/agents/ernährungsplaner.prompt.md
```

- `system_prompt` liegt in separater `.prompt.md` (gute opencode-Integration, klare Trennung Meta/Prompt).
- Klassifikator kennt die Agenten-Registry (names + keywords) wie in A; `ernährungsplaner` löst ab dem Demo-Agent.

### 3.3 Memory (per Agent)

- **Interface:** `AgentMemory` mit `get_context() -> str` (zusammengeführter Kontext für den Task-Prompt), `read_profile() -> dict`, `write_profile(key, value)`, `append_note(text)`
- **Implementierung:** `FileMemory`
  - `data/agents/<name>/profile.yaml` — strukturierte Fakten (z. B. `goal: Muskelaufbau`, `protein_target_g: 160`, `allergens: [gluten]`)
  - `data/agents/<name>/memory.md` — freie Notizen (Beobachtungen, Präferenzen, „der Nutzer mag keine Kohlhirse")
- **Injektion:** Der Runner liest den Kontext via `FileMemory.get_context()` und baut daraus den Task-Prompt (Aufgabe + Memory-Kontext).
- **Individuierung:** Die opencode-Agent-Prompts instruieren: relevantes Neues (Ziele, Präferenzen) wird in `profile.yaml`/`memory.md` persistentiert. Da die opencode-Session lokal auf Server 1 läuft, schreibt der Agent die Memory-Dateien direkt mit seinen File-Tools; der Python-Runner ist nur Leser. Der Agent individualisiert sich so über Zeit.
- **Erweiterungspunkt:** `AgentMemory` ist ein Interface → später `RagMemory` (Vector-Backend) austauschbar, ohne Runner-Änderungen.

### 3.4 Eskalation & HITL

Zwei Eskalationspfade, ein Gate:

| Pfad | Trigger | Quelle |
|---|---|---|
| 1 | Klassifikator: `remote_needed=true` oder Text enthält „erweiterten modus" | Router (vor Agent-Start) |
| 2 | Agent-Output enthält `[ESCALATE] <reason>` | Agent (während/nach Ausführung) |

- **HITL-Gate (LangGraph-Node):** TTS-Frage: *„Das ist komplexer als gedacht. Soll ich den Hauptrechner wecken?"* → Das System schaltet zurück in „listening" und wartet auf eine Sprachantwort (ja/nein) →
  - ja: MockServer2 (in B) → Antwort → TTS
  - nein: Agent bleibt lokal (bzw. idle, falls der Klassifikator eskaliert hat)
- In B bleibt Server 2 der Mock; echtes Wake/Modell = Subprojekt E.

### 3.5 Mealie-Anbindung (Ernährungsplaner)

- Mealie selbst gehostet (Docker), REST-API.
- MCP-Server: `rldiao/mealie-mcp-server` (fastmcp, 62 Tools inkl. `get_todays_mealplan`, Rezepte, Shopping-Listen, Kategorien, Tags, Food, Units, Meal-Plans).
- Start via `uvx git+https://github.com/rldiao/mealie-mcp-server`, Env: `MEALIE_BASE_URL`, `MEALIE_API_KEY` (API-Key **nicht im Repo**; per Umgebungsvariable).
- **Kein eigener Code** für Mealie — reine `opencode.json`-MCP-Konfiguration.
- Der Ernährungsplaner-Agent sieht so tägliches Essen, kann Pläne erstellen und individualisieren (Profile/Memory + Mealie-Daten).

## 4. opencode-Konfiguration

`opencode.json` (Root des max-Repos) definiert:

- **Agenten:** z. B. `ernährungsplaner` — Prompt (Referenz auf `.prompt.md`), erlaubte MCP-Server, evtl. Modell.
- **MCP-Server:** `mealie` via uvx + Env-Variablen.

Der Runner ruft `opencode run --agent ernährungsplaner "<task>"` auf. (Exakte CLI-Flags verifiziert der Implementer vor der Implementierung; die Interface bleibt stabil.)

## 5. Fehlerbehandlung

| Fehler | Verhalten |
|---|---|
| opencode-Launch schlägt fehl / Timeout | TTS-Fehlermeldung, zurück zu idle; Agent-Runner gibt `AgentResult` mit Fehler statt Exception |
| `[ESCALATE]` ohne User-Bestätigung | Keine Eskalation; lokal weiter oder idle |
| Mealie-MCP nicht erreichbar | Agent antwortet ohne Mealie-Daten + Hinweis; Kern-Anfrage lokal beantwortet |
| Memory-Dateien fehlen | Agent startet mit leerem Kontext (leeres profile/memory), initialisiert Dateien beim ersten Write |
| Klassifikator-Timeout | Fallback: remote-Routing (wie in A) |

## 6. Tests

- **Runner:** `MockAgentBackend` — normale Antwort, Eskalation, Timeout-Simulation; `[ESCALATE]`-Parsing.
- **Memory:** `FileMemory` mit tmp-dir-Isolation — profile lesen/schreiben, notes appenden, `get_context()`.
- **HITL-Flow:** Graph mit Fake-Transcriber/-Diarizer/-Classifier + MockAgentBackend: lokale Antwort, „erweiterten modus" → HITL → ja/nein-Pfade, `[ESCALATE]` → HITL.
- **E2E-Smoke (offline):** „Erstelle mir einen Ernährungsplan für Muskelaufbau" → Ernährungsplaner (mock) → Antwort; „…erweiterten modus" → HITL → MockServer2.
- **Kein Mealie-Test mit Live-Server** (offline); MCP-Config wird nur auf Gültigkeit geprüft (YAML/JSON parsen).

## 7. Projektstruktur (Erweiterung)

```
/home/user/max/
├── docs/superpowers/specs/
├── config/
│   ├── speakers.yaml
│   └── agents/
│       ├── ernährungsplaner.yaml
│       └── ernährungsplaner.prompt.md
├── data/agents/
│   └── ernährungsplaner/
│       ├── profile.yaml      # gitignored (individuelle Daten)
│       └── memory.md
├── src/max/
│   ├── agents/
│   │   ├── runner.py         # AgentRunner-Interface + Backends
│   │   ├── memory.py         # AgentMemory + FileMemory
│   │   └── nutrition.py      # Ernährungsplaner-Definition (Prompt-Wrapper, Defaults)
│   ├── pipeline/
│   ├── router/               # Graph-Erweiterung (agent_run, hitl)
│   ├── tts/
│   └── remote/
├── tests/
└── opencode.json             # Agenten + MCP (mealie)
```

## 8. Abgrenzung / YAGNI

- **Kein** vector-based Memory in B (Interface + FileMemory; RagMemory später).
- **Keine** echten opencode-Launches in Tests.
- Die Plattform ist von Grund auf **multi-agent tauglich** (generischer Runner, pro-Agent-Memory, pro-Fachbereich opencode-Agent). B liefert Ernährungsplaner als erstes Beispiel; weitere Agenten folgen auf derselben Plattform.
- **Kein** echtes Wake/Remote-Modell (Mock, wie in A; Subprojekt E).
- **Keine** Mealie-eigene Client-Code (nur MCP-Konfiguration).
