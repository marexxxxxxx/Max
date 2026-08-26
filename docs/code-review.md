# Code-Review — Max (Stand nach Subprojekt F)

Review aller Module: `src/max/**`, `config/**`, `scripts/**`. 124 Tests grün, aber
im Code finden sich Fehler und Logiklücken. Geordnet nach Schweregrad.

## Fix-Status (TDD-Session)

| # | Status |
|---|--------|
| 1 | Behoben: `config.DEFAULT_OLLAMA_MODEL` + `resolve_model` (Commit `14d45f6`) |
| 2 | False Positive: `OpencodeRunner._resolve_memory_dir`/`_resolve_path` lösen relativ zum Repo-Root auf — verifiziert durch Test |
| 3 | Behoben: `recorder.begin_request()` vor invoke in `run_smoke` (Commit `d597731`) |
| 4 | Behoben: erweitertes Wort-Set + Negations-Check (Commit `d6b4b3a`) |
| 5 | Behoben: Transcribe-Guard mit `STT_ERROR_ANSWER` + Diarization-Guards (Commit `e92d123`) |
| 6 | Behoben: `apply_interview_state` + `INTERVIEW_OVERFLOW_ANSWER` (Commit `11fc3ba`) |
| 7 | Behoben: Wake-Check im confirm-Node (Commit `af46824`) |
| 8 | Offen — braucht Mapping-Design (Voiceprint/Sprecher-IDs) |
| 9 | Behoben: `_poll_once` mit Keepalive + BrokenPipe (Commit `cfd16cf`) |
| 10, 11 | Vertagt — gehen in das UI-Redesign „A + B kombiniert“ ein |
| 12 | Behoben: HH:MM im Provider (Commit `70bc1fe`) |
| 13 | Behoben: Token-Fallback `len(content)//4` (Commit `02c5710`) |
| 14 | False Positive: `sounddevice` wird bereits lazy importiert — verifiziert durch Test |

## Hoch — Funktion/Fehler

### 1. Inkonsistente Ollama-Modelld_defaults
- `src/max/main.py:108` — Default `qwen2.5:9b`
- `scripts/system_test.py:65` — Default `qwen3.5:9b`
- Cache auf der Maschine enthält `qwen3.5:9b`. Ohne gesetztes `MAX_OLLAMA_MODEL`
  findet `main.py` das falsche Modell → Ollama-Error → Classifier-Fallback in
  `graph.py:99-101` schickt **jede** Anfrage remote.
- **Fix:** einheitlicher Default (`qwen3.5:9b`) oder eine Config-Datei.

### 2. CWD-abhängige Agent-Memory-Pfade
- `main.py:97-100`: `person_path` ist absolut, aber `memory_dir` aus den Agent-
  Profilen ist relativ (`data/agents/...`). `FileMemory` (memory.py:46-47)
  löst relativ zum Prozess-CWD auf. Startet man `main.py` nicht aus dem Repo-Root,
  landen Memory-Dateien am falschen Ort (oder es werden neue Verzeichnisse
  neben dem Repo angelegt).
- **Fix:** `memory_dir` im Runner absolut lösen (relativ zum Repo-Root).

### 3. Falsche Latenz im Smoke-Telemetry
- `smoke.py`: `run_smoke()` ruft `recorder.begin_request()` nie.
  `TelemetryRecorder.begin_ms` bleibt 0 → `latency_total_ms` = Zeit seit Epoch
  → absurd große Latenzwerte in `smoke_test.db`.
- **Fix:** in `run_smoke` vor dem Graph-Aufruf `recorder.begin_request()`.

### 4. HITL-Bestätigung: First-Word-Heuristik
- `hitl.py:17-27`: prüft nur das erste Wort.
  - "Ja, aber nur wenn du ihn nur für heute brauchst" → falsch als Ja gezählt.
  - STT-Varianten ("jaja", "ja ja.") fallen nicht in das Wortset → falsches Nein.
- **Fix:** kurzer LLM-Check oder erweiterte Wort-Liste + Negations-Bearbeitung.

### 5. Transcribe-Node ist ungeschützt
- `graph.py:87-93`: Whisper/Pyannote-Exceptions brechen die Pipeline ab
  (keine try/except). `diarization.py:13` setzt 16-Bit-PCM voraus;
  ungerade Byte-Länge → `numpy.frombuffer` Fehler.
- **Fix:** Exception-Handling im Node mit sinnvoller Fallback-Antwort.

### 6. Interview-Überlauf endet abrupt
- `main.py:148-151`: bei `interview_turns > MAX_INTERVIEW_TURNS` wird der Modus
  beendet, aber die aktuelle `[ASK]`-Frage wird trotzdem gesprochen → die Frage
  bleibt unbeantwortet, Interview endet ohne `[DONE]`.
- **Fix:** beim Überlauf eine Abschluss-Antwort geben (z. B. "Ich fasse zusammen …").

### 7. Remote-Wake/Ask-Scheitern ist unsichtbar
- `client.py:37-60`: Soft-Wake-Exception wird still geschluckt; wenn `wake()`
  False liefert, ruft `ask()` trotzdem an und liefert nur den generischen
  `FALLBACK`-Text. Der Nutzer erfährt nicht, dass Server 2 nicht erreichbar ist.
- **Fix:** unterschiedliche Meldungen (Wake fehlgeschlagen vs. Ask fehlgeschlagen),
  ggf. Retry.

## Mittel — Robustheit/UX

### 8. `resolve_speaker` ohne ID→Name-Mapping
- `config.py:17-21`: ein einzelner sprechender ID-Clusternamen liefert immer
  `registry[0]["name"]`, unabhängig vom tatsächlichen Diarization-Label
  (`SPEAKER_00`). Funktioniert nur mit einem registrierten Sprecher; mit zwei
  Speakern ist das Ergebnis falsch.
- **Fix:** Mapping-Datei oder stabile Zuordnung (z. B. via Voiceprint).

### 9. Dashboard-SSE ohne Keepalive
- `dashboard/server.py:119-128`: kein Keepalive (im Display-Server gibt es einen).
  Proxies/Intermediaries können idle-Verbindungen trennen; BrokenPipe beim
  Client-Disconnect ist nicht gehandelt.
- **Fix:** Keepalive-Comment + try/except um die wfile.write.

### 10. Dashboard-DOM unbounded
- `dashboard/static/index.html:77`: Rows werden nur vorgewoben, nie entfernt.
  Bei langem Betrieb wächst das DOM; snapshot begrenzt auf 50, aber
  streamende events addieren weiter.
- **Fix:** Cap (z. B. 200 Rows) und Alte entfernen.

### 11. Mirror: Doppel-Polling
- `display/static/index.html:61-67`: `setInterval(loadCards, 5000)` **und**
  SSE-Event → doppelter Reload bei jeder Änderung.
- **Fix:** SSE-only mit Fallback-Poll.

### 12. Uhr-Card zeigt rohen ISO-Zeitstempel
- `providers.py:54` + `display/static/index.html`: `data.time` ist z. B.
  `2026-08-26T12:34:56` — unlesbar.
- **Fix:** HH:MM-Format im Frontend oder Provider.

### 13. Token-Count aus Ollama unreliable
- `classify.py:44`: `resp.get("count", 0)` — je nach Ollama-Version API nicht
  immer vorhanden → Tokens 0.
- **Fix:** Fallback `estimate_tokens` wie im Recorder.

### 14. `main.py` startet ohne PortAudio nicht
- `main.py:85`: `import sounddevice` am Start → ohne PortAudio crash, auch
  wenn man nur Dashboard/Display will.
- **Fix:** Lazy-Import erst im Capture/TTS-Weg; oder `--no-audio`-Flag.

## Niedrig — Hardening

- `classify.py:22`: Greedy-Regex `\{.*\}` kann über das JSON hinaus greifen.
- `system_test.py:67`: `--real`-Smoke ohne `person_memory` → Person-Kontext
  wird im Smoke-Test nicht geübt.
- `telemetry/store.py` + Dashboard: zwei unabhängige SQLite-Verbindungen auf
  dieselbe DB, kein WAL → sporadisches Blocking bei gleichzeitigen Writes.
- `main.py:159-160`: stille Bestätigung (keine Audio) → Anfrage verworfen,
  ohne Telemetrie und ohne gesprochene Rückmeldung.
- `remote/service.py`: keine Auth (Default localhost; bei offener Bindung
  ungesichert).
- `capture_audio`: max. 30 s Capture, keine frühe Abbruch-Heuristik bei
  „keine Sprache" (volle 30 s Wartezeit).
- `person.py`: kein File-Lock (in Ordnung für Single-Process).

## Empfohlene Fix-Reihenfolge
1. #1 Modell-Default (produktiv sofort relevant)
2. #2 CWD-Pfade (Memory kaputt wenn anders gestartet)
3. #3 Smoke-Latenz (falsche Telemetrie)
4. #5 Transcribe-Guard (Crash-Safety)
5. #4 HITL-Heuristik (UX)
6. Rest nach Priorität.

Alle Fixes sind klein und lokal; Tests dazu sind mit dem bestehenden
TDD-Aufbau schnell geschrieben.
