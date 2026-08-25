import os
import numpy as np

from max.agents.registry import build_agents
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


def main():
    import sounddevice as sd

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    registry = load_speakers(os.path.join(root, "config", "speakers.yaml"))
    agents = build_agents(load_agent_profiles(os.path.join(root, "config", "agents")))
    graph = build_graph(
        WhisperTranscriber(),
        PyannoteDiarizer(),
        registry,
        OllamaClassifier(os.environ.get("MAX_OLLAMA_MODEL", "qwen2.5:9b")),
        agents,
        MockServer2(),
    )
    vad = Vad()
    tts = KokoroTts()
    while True:
        audio = capture_audio(vad)
        if audio is None:
            continue
        result = graph.invoke({"audio": audio})
        print(f"[Max] ({result['speaker']}): {result['answer']}")
        for chunk in tts.synthesize_chunks(result["answer"]):
            sd.play(np.frombuffer(chunk, dtype=np.int16), 22050)
            sd.wait()


if __name__ == "__main__":
    main()
