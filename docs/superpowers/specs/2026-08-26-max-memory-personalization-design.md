# Max — Subprojekt F: Memory-Personalisierung + System-Vor-Test (Design-Doc)

- **Datum:** 2026-08-26
- **Status:** Design vom Nutzer bestätigt (2026-08-26)
- **Vorausgesetzt:** Subprojekt A–E (alle abgeschlossen)
- **Repo:** `/home/user/max`

## 1. Zweck

1. **System-Vor-Test:** Einmaliger End-to-Test des gesamten Systems auf zwei realen Maschinen (kleine = Server 1, große = Server 2) mit echter Remote-Route. Zusätzlich ein wiederverwendbares Smoke-Test-Skript, das die Pipeline ohne Hardware (simuliertes Audio) durchläuft.
2. **Memory-Personalisierung:** Das bisherige agent-spezifische File-Memory wird um ein gemeinsames Personen-Profil erweitert, das alle Agenten lesen und aktualisieren können. Ein dedizierter Onboarding-Agent befüllt das Profil per Interview.

## 2. Scope

### Teil 1: System-Vor-Test
- **Zwei Maschinen:** Server 1 (kleine Maschine: Mic, Speaker, ollama 9B, opencode, Whisper, Pyannote) und Server 2 (große Maschine: `python -m max.remote.service` mit Ollama-Backend + großes Modell, Port 8090).
- **Echte Remote-Route:** `MAX_REMOTE_HOST` zeigt auf Server 2; Wake per Soft-Wake (Maschine ist bereits an) + optionales `MAX_POWER_SWITCH_CMD`.
- **Smoke-Test-Skript:** `scripts/system_test.py` läuft die Pipeline auf einer Maschine mit simuliertem Audio (WAV-Dateien) durch: VAD → STT → Diarization → Router → Agent (Mock oder opencode) → TTS (WAV-Datei) → Display-Card → Telemetrie. Output: Stage-by-Stage Summary.
- **Keine dritte Maschine nötig:** Die zwei vorhandenen Maschinen entsprechen exakt der Architektur (Server 1 + Server 2).

### Teil 2: Memory-Personalisierung
- **Gemeinsames Personen-Profil:** `data/memory/person.yaml` — strukturiertes Profil (Kategorien: Allergien, Ziele, Vorlieben, Beschränkungen), von allen Agenten geteilt.
- **Onboarding-Agent:** Neuer opencode-Agent `onboarding`, der per Interview (max. 3 Fragen pro Turn) das Personen-Profil befüllt. Multi-Turn über einen Interview-Mode im Graph.
- **Kreuz-Agenten-Personalität:** Jeder Agent bekommt in seinem Task-Prompt sowohl sein eigenes Memory als auch das Personen-Profil; alle Agenten dürfen neue dauerhafte Fakten ins Personen-Profil eintragen.
- **Strukturiertes Langzeitgedächtnis:** `person.yaml` mit festen Kategorien; Agents schreiben per Dateitools (wie bestehende Memory-Dateien), der Python-Runner liest nur.

**Nicht im Scope:** Pro-Sprecher-Profile (ein gemeinsames Profil), Vector-DB/Embedding-Retrieval, Verfallsystem, mehrere Personen.

## 3. Architektur & Komponenten

| Datei | Rolle |
|---|---|
| `src/max/agents/person.py` (neu) | `PersonMemory`: liest/schreibt `data/memory/person.yaml`; `get_context()` liefert kompakten Kontext-Text; `read()` → dict; `write_category(key, value)` idempotent. |
| `src/max/agents/runner.py` (geändert) | `build_task_message(task, memory_context, person_context, card_path, person_path)`: injiziert Personen-Profil-Kontext + Instruktion, neue dauerhafte Fakten in `person.yaml` einzutragen. `OpencodeRunner` nimmt optional `person_memory` entgegen. |
| `src/max/router/graph.py` (geändert) | Interview-Mode: State-Feld `interview_mode`. Wenn der Onboarding-Agent mit `[ASK]` endet, bleibt der Mode aktiv; der nächste Audio-Input wird ohne Klassifikation direkt dem Onboarding-Agent vorgelegt. `[DONE]` beendet den Mode. Marker werden aus der Antwort entfernt. |
| `src/max/main.py` (geändert) | Hält den Interview-Mode zwischen Aufrufen und trägt ihn in den Graph-State ein. |
| `config/agents/onboarding.yaml` (neu) | Agent-Profil: name `onboarding`, keywords `[onboarding, interview, profil, kennenlernen]`, `memory_dir: data/agents/onboarding`, `person_path: data/memory/person.yaml`. |
| `config/opencode/onboarding.prompt.md` (neu) | Interview-Prompt: max. 3 Fragen pro Turn, Antworten strukturiert in `person.yaml` eintragen (Kategorien: Allergien, Ziele, Vorlieben, Beschränkungen), Start mit `[ASK]`, Abschluss mit `[DONE]`. |
| `config/opencode/opencode.json` (geändert) | Eintrag `onboarding` mit Prompt-Referenz + Permissions (read/edit allow, external_directory allow). |
| `scripts/system_test.py` (neu) | Smoke-Test: WAV-Input → Pipeline → Output-Artefakte; `--mock` (Mock-Runner) oder `--real` (opencode). |

## 4. Interview-Flow

```
User: „Onboarding starten"
→ Klassifikator: agent=onboarding (keywords)
→ Onboarding-Agent: „Wie sind deine Allergien?" + [ASK]
→ Interview-Mode aktiv
User: „Ich vertrage keine Milch"
→ (ohne Klassifikation) direkt an Onboarding-Agent → profil.yaml Update + nächste Frage + [ASK]
...
→ Onboarding-Agent: „Alles notiert!" + [DONE]
→ Interview-Mode beendet
```

- **Marker:** `[ASK]` (weitere Fragen folgen), `[DONE]` (Interview beendet). Aus der gesprochenen Antwort entfernt.
- **Max. 3 Fragen pro Turn** (Prompt-Instruktion), damit TTS-Antworten kurz bleiben.
- **Robustheit:** Interview-Mode läuft maximal 10 Turns; danach zwangsweise `[DONE]` (Sicherheits-Stop in `main.py` oder Graph).

## 5. Personen-Profil-Struktur

```yaml
# data/memory/person.yaml
allergien: []
ziele: []
vorlieben: []
beschränkungen: []
```

- Kategorien als Listen (Appends, Deduplication durch den Agent per Dateitools).
- `PersonMemory.get_context()`: `Personen-Profil:\n  Allergien: ...\n  Ziele: ...` (leere Kategorien werden weggelassen).
- `person.yaml` existiert nicht → leeres Profil, Kontext = „(noch keine Erinnerungen)".
- Schreibzugriff nur über opencode-Agent-Dateitools (Python-Seite ist read-only außer `PersonMemory.write_category` für Tests).

## 6. System-Vor-Test-Plan (2 Maschinen)

**Voraussetzungen:**
- Kleine Maschine: Mic + Speaker, `uv sync`, ollama mit `qwen3.5:9b` (Classifier) und Whisper/Pyannote-Modelle.
- Große Maschine: `uv sync`, ollama mit großem Modell, Server-2-Dienst auf Port 8090.
- Beide im selben LAN.

**Ablauf (dokumentiert in `docs/superpowers/specs/2026-08-26-max-memory-personalization-design.md`):**
1. Server 2 starten: `python -m max.remote.service` (Ollama-Backend, großes Modell).
2. Server 1 starten: `MAX_REMOTE_HOST=<IP2> python -m max.main --serve-display --serve-dashboard` (env: `MAX_OLLAMA_MODEL=qwen3.5:9b`, `MAX_REMOTE_MODEL=<großes Modell>`).
3. Szenarien per Spracheingabe:
   - **Local-Route:** Ernährungsfrage → Ernährungsplaner → Antwort + Display-Card.
   - **Remote-Route:** medizinische Frage → HITL „Ja" → Wake → Server 2 → Antwort + Remote-Latenz in Telemetrie.
   - **Onboarding-Interview:** „Onboarding starten" → 2–3 Turns → `data/memory/person.yaml` befüllt.
   - **Personalisierung:** Ernährungsfrage nach Onboarding → Antwort berücksichtigt Personen-Profil.
   - **Telemetrie:** Dashboard (8081) zeigt alle Läufe inkl. Remote-Latenz.

**Smoke-Test ohne Hardware:** `uv run python scripts/system_test.py --mock` (simuliertes Audio, Mock-Runner, TTS nach WAV, Card, Telemetrie-Record).

## 7. Fehlerbehandlung

| Fehler | Verhalten |
|---|---|
| `person.yaml` fehlt/fehlformatiert | Leeres Profil, Pipeline läuft weiter |
| Onboarding-Agent crash/timeout | Wie üblich: Eskalation oder Fehlermeldung, Interview-Mode endet |
| Interview-Mode ohne `[DONE]` | Nach 10 Turns zwangsweise beendet |
| Server 2 unerreichbar | Bestehendes Verhalten (Subprojekt E) unverändert |

## 8. Tests

Alle offline:
- **PersonMemory:** Roundtrip, get_context, leeres Profil, Deduplication-Verhalten.
- **Runner:** Task-Mensagem enthält Personen-Kontext + person-Pfad-Instruktion; MockAgentRunner unverändert.
- **Graph:** Interview-Mode — `[ASK]` hält Mode, `[DONE]` beendet, Marker entfernt, 10-Turn-Limit.
- **Config:** `load_agent_profiles` liefert auch `onboarding`.
- **system_test.py:** Orchestrierungsfunktion mit Fake-Komponenten (Offline, deterministisch).

## 9. Annahmen & offene Punkte

- Ein gemeinsames Personen-Profil (eine Person im Haushalt); mehrere Personen wären ein späterer Ausbau.
- Der Onboarding-Agent ist der primäre Schreiber des Personen-Profils; andere Agenten dürfen es ergänzen.
- `scripts/system_test.py` ist ein Dev-Werkzeug (nicht Teil der Runtime).
- PortAudio ist in der Dev-Umgebung nicht verfügbar → Smoke-Test mit simuliertem Audio; der reale Live-Test läuft auf den beiden Maschinen mit Mic/Speaker.
