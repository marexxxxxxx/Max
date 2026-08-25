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


def main():
    import argparse
    import sounddevice as sd  # noqa: F841 — sicher, dass der Import am Start funktioniert

    parser = argparse.ArgumentParser(description="Max — lokaler Sprachassistent")
    parser.add_argument("--serve-display", action="store_true",
                        help="startet zusätzlich den Display-Server (localhost)")
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    registry = load_speakers(os.path.join(root, "config", "speakers.yaml"))
    profiles = load_agent_profiles(os.path.join(root, "config", "agents"))
    runner = OpencodeRunner(opencode_dir=os.path.join(root, "config", "opencode"))
    transcriber = WhisperTranscriber()
    graph = build_graph(
        transcriber,
        PyannoteDiarizer(),
        registry,
        OllamaClassifier(os.environ.get("MAX_OLLAMA_MODEL", "qwen2.5:9b")),
        profiles,
        runner,
        MockServer2(),
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

    while True:
        audio = capture_audio(vad)
        if audio is None:
            continue
        result = graph.invoke({"audio": audio})

        # HITL-Gate: remote-Routing braucht eine Sprachbestätigung des Users
        if result["awaiting_confirmation"]:
            print(f"[Max]: {result['answer']}")
            speak(tts, result["answer"])
            confirm_audio = capture_audio(vad)
            if confirm_audio is None:
                continue  # keine Bestätigung → remote-Routing verworfen
            confirm_text = transcriber.transcribe(confirm_audio)
            result = graph.invoke({
                "confirmation": confirm_text,
                "query": result["query"],
                "speaker": result["speaker"],
            })

        print(f"[Max] ({result['speaker']}): {result['answer']}")
        speak(tts, result["answer"])


if __name__ == "__main__":
    main()
