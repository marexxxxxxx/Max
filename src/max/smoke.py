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
    recorder.begin_request()
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
