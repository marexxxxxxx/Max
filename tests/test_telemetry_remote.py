import sqlite3

from max.telemetry.recorder import TelemetryRecorder
from max.telemetry.store import TelemetryStore


def test_store_migration_old_schema(tmp_path):
    path = str(tmp_path / "telemetry.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE requests (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts TEXT, speaker TEXT, text TEXT, agent TEXT,"
        "remote_needed INTEGER,"
        "tokens_router INTEGER, tokens_agent INTEGER, tokens_remote INTEGER,"
        "latency_stt_ms REAL, latency_router_ms REAL,"
        "latency_agent_ms REAL, latency_tts_ms REAL, latency_total_ms REAL)"
    )
    conn.commit()
    conn.close()
    store = TelemetryStore(path)
    rid = store.record({"speaker": "Alex", "text": "hallo"})
    row = store.recent(1)[0]
    assert row["id"] == rid
    assert row["latency_remote_ms"] is None
    store.close()


def test_recorder_remote_latency():
    r = TelemetryRecorder()
    r.begin_request()
    r.start("remote")
    r.end("remote")
    rec = r.build("Alex", "Testfrage", "", True)
    assert rec["latency_remote_ms"] is not None
