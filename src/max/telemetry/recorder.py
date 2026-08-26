"""Telemetrie-Recorder: misst Latenzen pro Stufe und sammelt Token-Zähler."""
import datetime
import time


class TelemetryRecorder:
    """Sammelt pro Anfrage: Stufen-Latenzen (ms) und Tokens pro Modell."""

    def __init__(self):
        self._stage_start: dict[str, float] = {}
        self._latencies: dict[str, float] = {}
        self._tokens = {"router": 0, "agent": 0, "remote": 0}
        self._total_start: float | None = None

    def begin_request(self):
        """Start der Total-Latenz (nach der Audio-Erfassung)."""
        self._total_start = time.monotonic()

    def start(self, stage: str):
        self._stage_start[stage] = time.monotonic()

    def end(self, stage: str):
        t0 = self._stage_start.pop(stage, None)
        if t0 is not None:
            self._latencies[stage] = (time.monotonic() - t0) * 1000.0

    def add_tokens(self, stage: str, n: int):
        if stage in self._tokens:
            self._tokens[stage] += int(n)

    def estimate_tokens(self, text: str) -> int:
        """Roh-Schätzung: Anzahl der Leerzeichen-getrennten Wörter."""
        return len((text or "").split())

    def build(self, speaker: str, text: str, agent: str, remote_needed: bool) -> dict:
        """Erzeugt das Record-Dict für den TelemetryStore."""
        total = None
        if self._total_start is not None:
            total = (time.monotonic() - self._total_start) * 1000.0
        return {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "speaker": speaker,
            "text": text,
            "agent": agent,
            "remote_needed": int(bool(remote_needed)),
            "tokens_router": self._tokens["router"],
            "tokens_agent": self._tokens["agent"],
            "tokens_remote": self._tokens["remote"],
            "latency_stt_ms": self._latencies.get("stt"),
            "latency_router_ms": self._latencies.get("router"),
            "latency_agent_ms": self._latencies.get("agent"),
            "latency_tts_ms": self._latencies.get("tts"),
            "latency_remote_ms": self._latencies.get("remote"),
            "latency_total_ms": total,
        }
