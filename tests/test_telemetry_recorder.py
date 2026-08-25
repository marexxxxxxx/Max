"""Tests für den TelemetryRecorder."""
import time

from max.telemetry.recorder import TelemetryRecorder


def test_latencies_measured():
    r = TelemetryRecorder()
    r.begin_request()
    r.start("stt")
    time.sleep(0.01)
    r.end("stt")
    record = r.build(speaker="alice", text="hallo", agent="demo", remote_needed=False)
    assert record["latency_stt_ms"] is not None and record["latency_stt_ms"] > 0
    assert record["latency_router_ms"] is None
    assert record["latency_total_ms"] is not None and record["latency_total_ms"] > 0


def test_tokens_and_remote_flag():
    r = TelemetryRecorder()
    r.add_tokens("router", 12)
    record = r.build(speaker="alice", text="hallo", agent="demo", remote_needed=True)
    assert record["tokens_router"] == 12
    assert record["tokens_agent"] == 0
    assert record["remote_needed"] == 1


def test_estimate_tokens():
    r = TelemetryRecorder()
    assert r.estimate_tokens("hallo welt") == 2
    assert r.estimate_tokens("") == 0


def test_missing_stage_is_none():
    r = TelemetryRecorder()
    record = r.build(speaker="alice", text="hallo", agent="demo", remote_needed=False)
    assert record["latency_stt_ms"] is None
    assert record["latency_router_ms"] is None
    assert record["latency_agent_ms"] is None
    assert record["latency_tts_ms"] is None
    assert record["latency_total_ms"] is None
