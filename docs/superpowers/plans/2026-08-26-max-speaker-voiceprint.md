# Max: Voiceprint-Sprecher-Mapping (Finding #8) — Implementierungsplan

**Goal:** Sprecher-Zuordnung über Voiceprints (pyannote speaker-embedding-3.0) statt der
fixen `resolve_speaker`-Heuristik, so dass Max mehrere registrierte Sprecher unterscheidet.

**Architecture:**
- Neue Pipeline-Komponente `src/max/pipeline/voiceprint.py`:
  `cosine_similarity`, `VoicePrintRegistry` (npz-Speichers under `config/voices/`),
  `label_embeddings` (mittleres Embedding pro Diarization-Label), `make_embedder` (lazy).
- Enrollment-CLI: `scripts/enroll_speaker.py --name X --audio sample.wav`.
- Integration in `build_graph`: nur bei `len(registry) > 1` + `voices_dir` Voiceprint-Pfad,
  sonst bestehender `resolve_speaker`-Fast-Path (ein Sprecher = keine Embedding-Kosten).

**Tech Stack:** pyannote.audio (bereits vorhanden), numpy .npz, pytest, uv.

**Global Constraints:**
- Deutsch in Docstrings/Comments/Commits; Commit-Style `max: <desc>`.
- TDD: erst Test, dann minimale Implementierung, Commit pro Aufgabe.
- `SAMPLE_RATE = 16000` (aus `src/max/pipeline/vad.py`).
- Audio: 16-Bit mono PCM, wie im Pipeline-Normformat.
- Pyannote nur lazy importieren (schwere Abhängigkeit), nur wenn Voiceprint-Pfad läuft.
- Threshold: `SIMILARITY_THRESHOLD = 0.4`; darunter oder ohne Enrollment → "unbekannt".

**File Structure:**
- Create: `src/max/pipeline/voiceprint.py`
- Create: `scripts/enroll_speaker.py`, `scripts/__init__.py`
- Modify: `src/max/router/graph.py`, `src/main.py`
- Create: `tests/test_voiceprint.py`, `tests/test_enroll_speaker.py`
- Modify: `tests/test_graph.py`, `docs/code-review.md`, `docs/installation.md`

## Task 1: VoicePrintRegistry (enroll/load/resolve)

**Files:**
- Create: `src/max/pipeline/voiceprint.py`
- Test: `tests/test_voiceprint.py`

**Step 1: Failing Test** (`tests/test_voiceprint.py`):

```python
import numpy as np

from max.pipeline.voiceprint import VoicePrintRegistry, cosine_similarity


def test_cosine_similarity_identical():
    assert cosine_similarity([1.0, 2.0], [1.0, 2.0]) == 1.0


def test_cosine_similarity_orthogonal():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_enroll_and_load(tmp_path):
    reg = VoicePrintRegistry(str(tmp_path))
    reg.enroll("Alex", np.array([0.5, 0.5]))
    assert reg.is_enrolled("Alex")
    emb = reg.load("Alex")
    assert emb.shape == (2,)
    assert emb[0] == 0.5
    assert reg.load("Beth") is None


def test_resolve_best_match(tmp_path):
    reg = VoicePrintRegistry(str(tmp_path))
    reg.enroll("Alex", np.array([1.0, 0.0]))
    reg.enroll("Beth", np.array([0.0, 1.0]))
    assert reg.resolve(["Alex", "Beth"], {"SPEAKER_00": np.array([0.9, 0.1])}) == "Alex"


def test_resolve_below_threshold(tmp_path):
    reg = VoicePrintRegistry(str(tmp_path))
    reg.enroll("Alex", np.array([1.0, 0.0]))
    # Orthogonales Embedding → Similarität 0 < Schwelle
    assert reg.resolve(["Alex"], {"SPEAKER_00": np.array([0.0, 1.0])}) == "unbekannt"


def test_resolve_no_enrollment(tmp_path):
    reg = VoicePrintRegistry(str(tmp_path))
    assert reg.resolve(["Alex"], {"SPEAKER_00": np.array([1.0, 0.0])}) == "unbekannt"
```

**Step 2: Lauf → Fail** (ImportError: Module `max.pipeline.voiceprint` nicht gefunden).

**Step 3: Implementierung** (`src/max/pipeline/voiceprint.py`):

```python
"""Voiceprint-Registry: Zuordnung von Diarization-Labels zu registrierten Sprechern.

Jeder registrierte Sprecher hat ein Referenz-Embedding als .npz unter <voices_dir>.
Zuordnung über Cosine-Similarity (Nearest-Neighbor); unterhalb der Schwelle
oder ohne Enrollment → "unbekannt".
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SIMILARITY_THRESHOLD = 0.4


def cosine_similarity(a, b) -> float:
    """Cosine-Similarity zweier Embeddings (0..1); Null-Vektoren liefern 0.0."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class VoicePrintRegistry:
    def __init__(self, voices_dir: str):
        self.voices_dir = Path(voices_dir)

    def path_for(self, name: str) -> Path:
        return self.voices_dir / f"{name}.npz"

    def is_enrolled(self, name: str) -> bool:
        return self.path_for(name).exists()

    def load(self, name: str) -> np.ndarray | None:
        """Referenz-Embedding eines Sprechers; None wenn nicht registriert."""
        if not self.is_enrolled(name):
            return None
        return np.load(self.path_for(name))["embedding"]

    def enroll(self, name: str, embedding) -> None:
        """Speichert das Referenz-Embedding eines Sprechers als .npz."""
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        np.savez(self.path_for(name), embedding=np.asarray(embedding, dtype=np.float32))

    def resolve(self, names: list[str], label_embeddings: dict[str, np.ndarray]) -> str:
        """Liefert den registrierten Namen mit der besten Übereinstimmung.

        label_embeddings: Diarization-Label → mittleres Embedding der Segmente.
        Unterhalb SIMILARITY_THRESHOLD oder ohne Enrollment → "unbekannt".
        """
        best_name = "unbekannt"
        best_sim = SIMILARITY_THRESHOLD
        for name in names:
            ref = self.load(name)
            if ref is None:
                continue
            for emb in label_embeddings.values():
                sim = cosine_similarity(ref, emb)
                if sim > best_sim:
                    best_sim = sim
                    best_name = name
        return best_name
```

**Step 4: Lauf** → `uv run pytest tests/test_voiceprint.py -q` → 6 grün.

**Step 5: Commit** → `max: VoicePrintRegistry mit Cosine-Similarity-Zuordnung`

## Task 2: label_embeddings (Segment-Slices → mittlere Embeddings)

**Files:**
- Modify: `src/max/pipeline/voiceprint.py`
- Test: `tests/test_voiceprint.py` (ergänzen)

**Step 1: Failing Tests** (Anhang an `tests/test_voiceprint.py`):

```python
def test_label_embeddings(tmp_path):
    import numpy as np
    from max.pipeline.voiceprint import label_embeddings

    class FakeEmbedder:
        def __call__(self, arr):
            return np.array([arr.size, 1.0])

    # 3 Sekunden à 16000 Samples
    audio = b"\x00\x00" * 48000
    segments = [("A", 0.0, 1.0), ("A", 1.0, 1.5), ("B", 2.0, 3.0)]
    result = label_embeddings(audio, segments, FakeEmbedder())
    assert len(result) == 2
    assert result["A"][0] == (16000 + 8000) / 2
    assert result["B"][0] == 16000


def test_label_embeddings_skips_empty_slices():
    import numpy as np
    from max.pipeline.voiceprint import label_embeddings

    class FakeEmbedder:
        def __call__(self, arr):
            raise AssertionError("Embedder darf mit leerem Slice nicht aufgerufen werden")

    audio = b"\x00\x00" * 32000
    result = label_embeddings(audio, [("A", 0.0, 1.0), ("B", 5.0, 6.0)], FakeEmbedder())
    assert list(result.keys()) == ["A"]
```

**Step 2: Lauf → Fail** (`ImportError: cannot import name 'label_embeddings'`).

**Step 3: Implementierung** (Anhang an `src/max/pipeline/voiceprint.py`):

```python
SAMPLE_RATE = 16000


def label_embeddings(audio: bytes, segments, embedder) -> dict[str, np.ndarray]:
    """Mittleres Embedding pro Diarization-Label aus den Segment-Slices.

    audio: 16-Bit-PCM (mono, 16 kHz), segments: (label, start, end) in Sekunden.
    Leere Slices (außerhalb des Audio) werden übersprungen.
    """
    if len(audio) % 2:
        audio = audio[:-1]
    data = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
    sums = {}
    counts = {}
    for label, start, end in segments:
        i0 = int(start * SAMPLE_RATE)
        i1 = min(int(end * SAMPLE_RATE), len(data))
        if i1 <= i0:
            continue
        emb = np.asarray(embedder(data[i0:i1]), dtype=np.float64)
        sums[label] = sums.get(label, np.zeros_like(emb)) + emb
        counts[label] = counts.get(label, 0) + 1
    return {label: sums[label] / counts[label] for label in sums}


def make_embedder():
    """Erzeugt den Pyannote-Embedding-Extractor (lazy, nur bei Bedarf)."""
    from pyannote.audio import Pipeline
    return Pipeline.from_pretrained("pyannote/speaker-embedding-3.0")
```

**Step 4: Lauf** → `uv run pytest tests/test_voiceprint.py -q` → 8 grün.

**Step 5: Commit** → `max: label_embeddings und make_embedder für Voiceprints`

## Task 3: enroll_speaker.py (Enrollment-CLI)

**Files:**
- Create: `scripts/enroll_speaker.py`, `scripts/__init__.py` (leer, macht `scripts` importierbar)
- Test: `tests/test_enroll_speaker.py`

**Step 1: Failing Test** (`tests/test_enroll_speaker.py`):

```python
import wave

import numpy as np

import scripts.enroll_speaker as enroll


def _write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        for s in samples:
            w.writeframes(s.to_bytes(2, "little", signed=True))


def test_enroll_speaker_from_wav(tmp_path, monkeypatch):
    wav_path = str(tmp_path / "s.wav")
    _write_wav(wav_path, [100, 200, 300, 400])

    class FakeEmbedder:
        def __call__(self, arr):
            return np.array([arr.size, 1.0])

    import max.pipeline.voiceprint as vp
    monkeypatch.setattr(vp, "make_embedder", lambda: FakeEmbedder())

    enroll.main(["--name", "Alex", "--audio", wav_path, "--voices-dir", str(tmp_path / "voices")])

    emb = np.load(str(tmp_path / "voices" / "Alex.npz"))["embedding"]
    assert emb.shape == (2,)
    assert emb[0] == 4
```

**Step 2: Lauf → Fail** (ImportError: No module named `scripts.enroll_speaker`).

**Step 3: Implementierung** (`scripts/enroll_speaker.py`):

```python
"""Enrolliert einen Sprecher: Voiceprint aus einer WAV-Datei (16 kHz, mono, 16-Bit).

Usage:
    uv run python scripts/enroll_speaker.py --name Alex --audio sample.wav
"""
import argparse
import os
import wave

import numpy as np

from max.pipeline.voiceprint import VoicePrintRegistry


def read_samples(path: str) -> list[int]:
    """Liest die PCM-Samples einer WAV-Datei (mono, 16-Bit)."""
    with wave.open(path, "rb") as w:
        assert w.getnchannels() == 1, "WAV muss mono sein"
        assert w.getsampwidth() == 2, "WAV muss 16-Bit sein"
        return list(w.readframes(w.getnframes()))


def main(argv=None):
    """Enrolliert einen Sprecher aus einer WAV-Datei (Default: config/voices)."""
    parser = argparse.ArgumentParser(description="Sprecher-Enrollment via Voiceprint")
    parser.add_argument("--name", required=True, help="Name des Sprechers")
    parser.add_argument("--audio", required=True, help="WAV-Datei (16 kHz, mono, 16-Bit)")
    parser.add_argument("--voices-dir", default=None, help="Speicherort (Default: config/voices)")
    args = parser.parse_args(argv)

    from max.pipeline.voiceprint import make_embedder

    samples = read_samples(args.audio)
    audio = bytearray()
    for s in samples:
        audio += s.to_bytes(2, "little", signed=True)
    data = np.frombuffer(bytes(audio), dtype=np.int16).astype(np.float32) / 32768.0
    embedding = make_embedder()(data)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    voices_dir = args.voices_dir or os.path.join(root, "config", "voices")
    VoicePrintRegistry(voices_dir).enroll(args.name, embedding)
    print(f"Registriert: {args.name}")


if __name__ == "__main__":
    main()
```

**Step 4: Lauf** → `uv run pytest tests/test_enroll_speaker.py -q` → 1 grün.

**Step 5: Commit** → `max: enroll_speaker.py für Voiceprint-Enrollment`

## Task 4: Integration in build_graph + main.py

**Files:**
- Modify: `src/max/router/graph.py`, `src/max/main.py`
- Test: `tests/test_graph.py` (ergänzen)

**Step 1: Failing Tests** (Anhang an `tests/test_graph.py`):

```python
class FakeDiarizerTwo:
    def diarize(self, audio):
        return [("SPEAKER_00", 0.0, 1.0), ("SPEAKER_01", 1.0, 2.0)]


def test_voiceprint_resolution(tmp_path):
    import numpy as np
    from max.pipeline.voiceprint import VoicePrintRegistry

    reg_dir = tmp_path / "voices"
    reg = VoicePrintRegistry(str(reg_dir))
    reg.enroll("Alex", np.array([1.0, 0.0]))
    reg.enroll("Beth", np.array([0.0, 1.0]))

    class FakeEmbedder:
        def __call__(self, arr):
            return np.array([float(np.asarray(arr, dtype=np.float64).sum()), 0.0])

    # 2 Sekunden: erste Sekunde Sample +1, zweite Sekunde Sample -1
    audio = (b"\x01\x00" * 16000 * 2) + (b"\xff\x00" * 16000 * 2)

    g = build_graph(
        FakeTranscriber(), FakeDiarizerTwo(),
        [{"name": "Alex"}, {"name": "Beth"}],
        FakeClassifier(agent="ernaehrungsplaner"), _profiles(), MockAgentRunner(), MockServer2(),
        voices_dir=str(reg_dir), embedder=FakeEmbedder(),
    )
    result = g.invoke({"audio": audio})
    assert result["speaker"] == "Alex"


def test_voiceprint_below_threshold(tmp_path):
    import numpy as np
    from max.pipeline.voiceprint import VoicePrintRegistry

    reg_dir = tmp_path / "voices"
    reg = VoicePrintRegistry(str(reg_dir))
    reg.enroll("Alex", np.array([1.0, 0.0]))

    class FakeEmbedder:
        def __call__(self, arr):
            return np.array([0.0, 0.0])

    audio = b"\x00\x00" * 32000
    g = build_graph(
        FakeTranscriber(), FakeDiarizerTwo(),
        [{"name": "Alex"}, {"name": "Beth"}],
        FakeClassifier(agent="ernaehrungsplaner"), _profiles(), MockAgentRunner(), MockServer2(),
        voices_dir=str(reg_dir), embedder=FakeEmbedder(),
    )
    result = g.invoke({"audio": audio})
    assert result["speaker"] == "unbekannt"
```

**Step 2: Lauf → Fail** (`TypeError: build_graph() got an unexpected keyword argument 'voices_dir'`).

**Step 3: Implementierung** (`src/max/router/graph.py`):

- Signatur: `def build_graph(transcriber, diarizer, registry, classifier, profiles, runner, server2, recorder=None, voices_dir=None, embedder=None):`
- In `transcribe`: `speaker = resolve_speaker([...])` ersetzen durch `speaker = _resolve_speaker(state["audio"], segments)`.
- Neuer Helper innerhalb von `build_graph`:

```python
    def _resolve_speaker(audio, segments):
        # Ein registrierter Sprecher → bestehender Fast-Path (keine Embedding-Kosten)
        if len(registry) <= 1 or not voices_dir:
            return resolve_speaker([s[0] for s in segments], registry)
        from max.pipeline.voiceprint import VoicePrintRegistry, label_embeddings, make_embedder
        emb = embedder or make_embedder()
        label_emb = label_embeddings(audio, segments, emb)
        return VoicePrintRegistry(voices_dir).resolve(
            [sp["name"] for sp in registry], label_emb
        )
```

- `src/max/main.py`: im `build_graph(...)`-Aufruf (ca. Zeile 128) zusätzlich
  `voices_dir=os.path.join(root, "config", "voices")` übergeben.

**Step 4: Lauf** → `uv run pytest tests/test_graph.py tests/test_voiceprint.py tests/test_enroll_speaker.py -q` → alle grün (incl. Bestehende 145 Tests).

**Step 5: Commit** → `max: Voiceprint-Zuordnung im Graph für mehrere Sprecher`

## Task 5: Doku-Updates

**Files:**
- Modify: `docs/code-review.md`, `docs/installation.md`

**Step 1:** In `docs/code-review.md` Fix-Status-Tabelle, Zeile #8 ersetzen durch:

```
| 8 | Geplant — Voiceprint-Plan in `docs/superpowers/plans/2026-08-26-max-speaker-voiceprint.md` (pausiert) |
```

Außerdem Kopfzeile "124 Tests grün" durch aktuelle Testzahl ersetzen.

**Step 2:** In `docs/installation.md` neuen Abschnitt anfügen:

```markdown
## Sprecher-Enrollment (mehrere Sprecher)

Wenn mehrere Personen mit Max sprechen, muss jeder Sprecher einmalig enrolliert werden:

1. Kurze Sprachprobe (ca. 10–30 s) als WAV (16 kHz, mono, 16-Bit) aufnehmen.
2. Enrollen:

   uv run python scripts/enroll_speaker.py --name Alex --audio sample.wav

Das Voiceprint landet in `config/voices/<name>.npz`. Bei mehreren registrierten
Sprechern erkennt Max per Voiceprint, wer gesprochen hat; unregistrierte Stimmen
werden als "unbekannt" gemeldet. Mit nur einem registrierten Sprecher bleibt der
Fast-Path ohne Embedding.
```

**Step 3: Commit** → `max: Doku-Updates Voiceprint (code-review #8 + Installation)`

## Final Verification

- `uv run pytest -q` → alle Tests grün.
- `uv run python scripts/system_test.py --mock` → Smoke-Test ok.
- Manuell (optional, nach Real-Maschinen-Verbindungs-Test): Enrollment einer zweiten Person und Dialog mit zwei Sprechern.

## Open Items (nicht Teil dieses Plans)
- Real 2-Maschinen-Test (Maschinen noch nicht verbunden).
- Mikrofon-basierte Enrollment (nur WAV-Dateien jetzt; YAGNI).
