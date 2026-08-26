import os
import numpy as np

from max.agents.runner import OpencodeRunner
from max.config import load_agent_profiles, load_speakers
from max.pipeline.diarization import PyannoteDiarizer
from max.pipeline.stt import WhisperTranscriber
from max.pipeline.vad import SAMPLE_RATE, frame_bytes, Vad
from max.remote.server2 import MockServer2
from max.router.classify import OllamaClassifier
from max.router.graph import build_graph
from max.telemetry.recorder import TelemetryRecorder
from max.telemetry.store import TelemetryStore
from max.tts.kokoro_tts import KokoroTts


def capture_audio(vad: Vad, max_seconds: float = 30.0, end_silence_frames: int = 5):
    import sounddevice as sd

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


def speak(tts, text: str) -> None:
    """Spricht Text per TTS (sounddevice wird lazy importiert)."""
    import sounddevice as sd

    for chunk in tts.synthesize_chunks(text):
        sd.play(np.frombuffer(chunk, dtype=np.int16), 22050)
        sd.wait()


def speak_rec(tts, recorder, text: str) -> None:
    """TTS mit Telemetrie: Latenz misst, Fehler crashen nie die Pipeline."""
    try:
        recorder.start("tts")
    except Exception as e:
        print(f"[Max] Telemetrie-Error: {e}")
    speak(tts, text)
    try:
        recorder.end("tts")
    except Exception as e:
        print(f"[Max] Telemetrie-Error: {e}")


def make_server2(env=None):
    """RemoteServer2Client wenn MAX_REMOTE_HOST gesetzt, sonst MockServer2 (Dev-Default)."""
    env = env if env is not None else os.environ
    host = env.get("MAX_REMOTE_HOST", "")
    if not host:
        return MockServer2()
    from max.remote.client import RemoteServer2Client
    from max.remote.wake import CommandPowerSwitch
    power = CommandPowerSwitch(env["MAX_POWER_SWITCH_CMD"]) if env.get("MAX_POWER_SWITCH_CMD") else None
    return RemoteServer2Client(
        host=host,
        port=int(env.get("MAX_REMOTE_PORT", "8090")),
        power_switch=power,
        timeout=float(env.get("MAX_REMOTE_TIMEOUT", "60")),
        wake_timeout=float(env.get("MAX_REMOTE_WAKE_TIMEOUT", "120")),
    )


def main():
    import argparse
    import sounddevice as sd  # noqa: F841 — sicher, dass der Import am Start funktioniert

    parser = argparse.ArgumentParser(description="Max — lokaler Sprachassistent")
    parser.add_argument("--serve-display", action="store_true",
                        help="startet zusätzlich den Display-Server (localhost)")
    parser.add_argument("--serve-dashboard", action="store_true",
                        help="startet zusätzlich das Web-Dashboard (localhost)")
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    registry = load_speakers(os.path.join(root, "config", "speakers.yaml"))
    profiles = load_agent_profiles(os.path.join(root, "config", "agents"))
    runner = OpencodeRunner(opencode_dir=os.path.join(root, "config", "opencode"))
    transcriber = WhisperTranscriber()
    recorder = TelemetryRecorder()
    store = TelemetryStore(os.path.join(root, "data", "telemetry.db"))
    graph = build_graph(
        transcriber,
        PyannoteDiarizer(),
        registry,
        OllamaClassifier(os.environ.get("MAX_OLLAMA_MODEL", "qwen2.5:9b")),
        profiles,
        runner,
        make_server2(),
        recorder=recorder,
    )
    vad = Vad()
    tts = KokoroTts()

    if args.serve_display:
        from max.display.server import DisplayServer
        card_dir = os.path.join(root, "data", "display", "cards")
        DisplayServer(
            card_dir,
            calendar_path=os.path.join(root, "config", "calendar.json"),
        ).start_in_thread(port=int(os.environ.get("MAX_DISPLAY_PORT", "8080")))

    if args.serve_dashboard:
        from max.dashboard.server import DashboardServer
        DashboardServer(
            db_path=os.path.join(root, "data", "telemetry.db"),
            agents_dir=os.path.join(root, "config", "agents"),
        ).start_in_thread(port=int(os.environ.get("MAX_DASHBOARD_PORT", "8081")))

    while True:
        audio = capture_audio(vad)
        if audio is None:
            continue
        recorder.begin_request()
        result = graph.invoke({"audio": audio})

        # HITL-Gate: remote-Routing braucht eine Sprachbestätigung des Users
        if result["awaiting_confirmation"]:
            print(f"[Max]: {result['answer']}")
            speak_rec(tts, recorder, result["answer"])
            confirm_audio = capture_audio(vad)
            if confirm_audio is None:
                continue  # keine Bestätigung → remote-Routing verworfen
            confirm_text = transcriber.transcribe(confirm_audio)
            first = result
            result = graph.invoke({
                "confirmation": confirm_text,
                "query": first["query"],
                "speaker": first["speaker"],
            })
            # Bestätigungsrunde kennt text/agent/remote_needed nicht — aus der ersten Runde übernehmen
            result["text"] = first.get("text", first.get("query", ""))
            result["agent"] = first.get("agent", "")
            result["remote_needed"] = bool(first.get("remote_needed", False))

        print(f"[Max] ({result['speaker']}): {result['answer']}")
        speak_rec(tts, recorder, result["answer"])

        # Telemetrie speichern: Fehler loggen, Pipeline nie crashen
        try:
            store.record(recorder.build(
                speaker=result["speaker"],
                text=result.get("text", result.get("query", "")),
                agent=result.get("agent", ""),
                remote_needed=bool(result.get("remote_needed", False)),
            ))
        except Exception as e:
            print(f"[Max] Telemetrie-Error: {e}")


if __name__ == "__main__":
    main()
