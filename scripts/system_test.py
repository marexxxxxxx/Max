"""Smoke-Test-CLI: ein Audio-Input durch die komplette Pipeline.

Usage:
  uv run python scripts/system_test.py --mock
  uv run python scripts/system_test.py --real --audio /pfad/zur.wav

--mock: Offline-Komponenten (Fake-Transkription, Mock-Runner), deterministisch,
         keine Modelle nötig.
--real: Echte Pipeline (Whisper, Pyannote, Ollama, opencode-Runner, Kokoro-TTS).
         Braucht: ollama (MAX_OLLAMA_MODEL), opencode, Kokoro. Audio: WAV-Datei.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from max.smoke import run_smoke


class FakeTranscriber:
    def transcribe(self, audio):
        return "Plane mir einen Ernährungsplan"


class FakeDiarizer:
    def diarize(self, audio):
        return [("SPEAKER_00", 0.0, 1.0)]


class FakeClassifier:
    def classify(self, text, agents):
        from max.router.classify import Classification
        return Classification("ernaehrungsplaner", 0.9, False)


class FakeTts:
    def synthesize_chunks(self, text):
        return [b"xx" * max(1, len(text.split()))]


def main():
    parser = argparse.ArgumentParser(description="Max Smoke-Test")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--audio", default=None)
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if args.real:
        if not args.audio:
            print("Fehler: --real braucht --audio <wav>")
            sys.exit(1)
        with open(args.audio, "rb") as f:
            audio = f.read()
        from max.agents.runner import OpencodeRunner
        from max.pipeline.diarization import PyannoteDiarizer
        from max.pipeline.stt import WhisperTranscriber
        from max.remote.server2 import MockServer2
        from max.router.classify import OllamaClassifier
        from max.tts.piper_tts import PiperTts
        from max.config import DEFAULT_OLLAMA_MODEL, load_agent_profiles
        transcriber = WhisperTranscriber()
        diarizer = PyannoteDiarizer()
        classifier = OllamaClassifier(os.environ.get("MAX_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL))
        profiles = load_agent_profiles(os.path.join(root, "config", "agents"))
        runner = OpencodeRunner(opencode_dir=os.path.join(root, "config", "opencode"))
        server2 = MockServer2()
        tts = PiperTts()
    else:
        audio = b"xx"
        from max.agents.runner import MockAgentRunner
        from max.remote.server2 import MockServer2
        profiles = [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}]
        transcriber = FakeTranscriber()
        diarizer = FakeDiarizer()
        classifier = FakeClassifier()
        runner = MockAgentRunner()
        server2 = MockServer2()
        tts = FakeTts()

    registry = [{"name": "Alex"}]
    store_path = os.path.join(root, "data", "smoke_test.db")
    summary = run_smoke(audio, transcriber, diarizer, registry, classifier, profiles,
                        runner, server2, tts=tts, store_path=store_path)
    print("=== Smoke-Test Summary ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("OK")


if __name__ == "__main__":
    main()
