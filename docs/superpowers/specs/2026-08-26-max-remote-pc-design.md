# Max — Subprojekt E: Remote-PC (echt) (Design-Doc)

- **Datum:** 2026-08-26
- **Status:** Design vom Nutzer bestätigt (2026-08-26)
- **Vorausgesetzt:** Subprojekt A (Skeleton), B (Agenten-Plattform), C (Smart Mirror), D (Web-Dashboard + Telemetrie)
- **Repo:** `/home/user/max`

## 1. Zweck

Der `MockServer2` wird ersetzt durch eine echte Remote-Anbindung: Server 2 als eigener Prozess (HTTP-Dienst), konfigurierbares großes Modell, zweistufiger Wake (HTTP-Soft-Wake + abstraktes Power-Switch-Backend) und Fehlerbehandlung gemäß Haupt-Design-Doc.

## 2. Scope

- **Kommunikation:** HTTP über LAN (Server 1 → Server 2, Antwort zurück), Request/Response.
- **Wake:** zweistufig — (1) HTTP-Soft-Wake, (2) falls Server 2 unerreichbar: abstraktes Power-Switch-Backend + Health-Polling bis Server 2 up ist.
- **Großes Modell:** konfigurierbar — Ollama auf Server 2 als Default (Modellname via Config), Generic-HTTP-Endpunkt als Option, Stub für Dev/Tests.
- **Telemetrie:** Remote-Latenz (`latency_remote_ms`) und `tokens_remote` pro Anfrage.
- **Dev/Tests:** lokale 2-Prozess-Lösung — Server-2-Dienst als eigener Prozess auf localhost, Client spricht ihn an; Produktion via `MAX_REMOTE_HOST`.

**Nicht im Scope:** echtes Wake-on-LAN Magic Packet (das abstrakte Backend lässt es später zu), Docker/deployment-Skripte, Streaming-Antworten von Server 2, Auth.

## 3. Architektur & Komponenten

Alles stdlib (urllib, http.server, threading) — keine neuen Dependencies.

| Datei | Rolle |
|---|---|
| `src/max/remote/server2.py` | `MockServer2` (unverändert, Dev-Default + Tests) |
| `src/max/remote/client.py` | `RemoteServer2Client(host, port, ...)`: `wake()` + `ask(query)` per HTTP. Gleiche Interface wie `MockServer2` (duck-typing) → `graph.py` braucht nur kleine Anpassungen (Remote-Latenz-Messung). |
| `src/max/remote/service.py` | Server-2-Dienst: stdlib `ThreadingHTTPServer`, Endpoints `/health`, `/wake`, `/ask`. Start: `python -m max.remote.service` (eigener Prozess, unabhängig von `main.py`). |
| `src/max/remote/backends.py` | `OllamaBackend` (Default, ruft die ollama HTTP-API auf Server 2 ab), `GenericHttpBackend` (beliebiger Endpunkt), `StubBackend` (Dev/Tests). Injected per Constructor. |
| `src/max/remote/wake.py` | Abstraktes Wake-Backend: `PowerSwitch` mit `trigger()`. Implementierung `CommandPowerSwitch` via env `MAX_POWER_SWITCH_CMD` (z. B. HTTP-Request an das WLAN-Power-Switch-Gerät) — hardware-agnostisch. |

`main.py`: `MAX_REMOTE_HOST` gesetzt → `RemoteServer2Client`, sonst `MockServer2` (Dev-Verhalten bleibt unverändert).

## 4. Wake-Flow

```
wake():
  1. POST /wake (Soft-Wake) → Erfolg → True
  2. Unreachable → power_switch.trigger() → poll GET /health bis up
     (Timeout: MAX_REMOTE_WAKE_TIMEOUT, Default 120 s, Fortschritt-Prints ~alle 10 s)
  3. Timeout → False
```

- `ask(query)`: POST `/ask` → Antworttext. Bei unerreichbarem Server/Timeout → Fallback-Text **„Der Hauptrechner ist nicht erreichbar“** (TTS, Pipeline zurück zu idle).

## 5. Server-2-Service

- Port: `MAX_REMOTE_PORT`, Default **8090**.
- Endpoints:

| Endpoint | Funktion |
|---|---|
| `GET /health` | `{"status": "ok"}` |
| `POST /wake` | Modell warm halten / lazy-Load auslösen |
| `POST /ask` | `{"query": ...}` → `{"answer": ..., "tokens": ...}` |

- Backend per Constructor injiziert; Modell wird lazy geladen (erster `/wake` oder `/ask`).
- `OllamaBackend`: ollama HTTP-API auf Server 2 (Port 11434), Modellname via `MAX_REMOTE_MODEL`; liefert Token-Count aus der API.
- `GenericHttpBackend`: konfigurierbare URL + Header für beliebige Model-APIs.
- `StubBackend`: feste Antwort, für Dev/Tests.

## 6. Configuration (env)

| Variable | Bedeutung | Default |
|---|---|---|
| `MAX_REMOTE_HOST` | Adresse von Server 2 | leer → `MockServer2` (Dev-Default) |
| `MAX_REMOTE_PORT` | Port des Server-2-Dienstes | 8090 |
| `MAX_REMOTE_MODEL` | Großes Modell auf Server 2 | konfigurierbar (ollama Default) |
| `MAX_REMOTE_TIMEOUT` | Timeout pro Query | 60 s |
| `MAX_REMOTE_WAKE_TIMEOUT` | Boot-Wartezeit (Health-Poll) | 120 s |
| `MAX_POWER_SWITCH_CMD` | Befehl für den Power-Switch | none |

## 7. Telemetrie (Erweiterung von D)

- `confirm`-Node des Graphen: `recorder.start("remote")` / `end("remote")` um wake+ask → Remote-Latenz gemessen.
- `telemetry.db`: neue Spalte `latency_remote_ms` (in `CREATE TABLE` + `ALTER TABLE ADD COLUMN` für bestehende DBs, fehlertolerant).
- `tokens_remote`: wie bisher — echter Count vom Backend, sonst Whitespace-Split-Estimate.
- Dashboard: Requests-Tabelle zeigt die neue Latenz-Spalte an.

## 8. Fehlerbehandlung

| Fehler | Verhalten |
|---|---|
| Server 2 unerreichbar (Wake) | Power-Switch-Trigger + Health-Poll; Timeout → `wake() = False` |
| `ask` ohne Antwort/Timeout | Fallback-Text „Der Hauptrechner ist nicht erreichbar“ per TTS, Pipeline weiter |
| Power-Switch nicht konfiguriert | Nur Soft-Wake; kein Crash |
| Client-Fehler dürfen Pipeline nie crashen (gleiche Guard-Pattern wie Telemetrie) |

## 9. Tests

Alle offline, stdlib only (urllib, http.server, threading):

- **Service + StubBackend** auf freiem Port: `/health`, `/wake`, `/ask` funktionieren.
- **RemoteServer2Client** gegen lokalen Service: `wake()` → True, `ask()` → Antwort; gegen unerreichbaren Port: `wake()` → False, `ask()` → Fallback-Text.
- **Power-Switch:** Fake-Trigger + Health-Polling innerhalb des Timeouts.
- **OllamaBackend:** gegen Fake-Ollama-HTTP-Server (stdlib), liefert `answer` + `count`.
- **Graph-E2E:** `build_graph` mit `RemoteServer2Client` gegen lokalen Service; HITL „ja“ → echte Antwort aus dem Service; Telemetrie-Record enthält `latency_remote`.
- **MockServer2** bleibt unverändert (Dev-Default + bestehende Tests).

## 10. Annahmen & offene Punkte

- Im Repo-Umfeld gibt es keine echte zweite Maschine → die lokale 2-Prozess-Lösung ist Referenz; in Produktion zeigt `MAX_REMOTE_HOST` auf die reale Maschine.
- Power-Switch ist ein abstraktes Backend (Befehl via env); konkrete Hardware (z. B. WLAN-Power-Switch-Gerät) wird nicht im Code fixiert — WoL ist später über dieselbe Schnittstelle möglich.
- Keine Streaming-Antworten von Server 2 (einmalige Antwort, TTS wie bisher).
- Server-2-Dienst läuft als separater Prozess (`python -m max.remote.service`), unabhängig von `main.py`.

## 11. Projektstruktur (Erweiterung)

```
src/max/remote/
├── __init__.py
├── server2.py        # MockServer2 (unverändert)
├── client.py         # RemoteServer2Client
├── service.py        # Server-2-HTTP-Dienst
├── backends.py       # OllamaBackend / GenericHttpBackend / StubBackend
└── wake.py           # PowerSwitch-Abstraktion
```
