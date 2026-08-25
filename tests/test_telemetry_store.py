from max.telemetry.store import TelemetryStore


def _store(tmp_path):
    return TelemetryStore(str(tmp_path / "telemetry.db"))


def test_record_and_recent(tmp_path):
    store = _store(tmp_path)
    r1 = store.record(
        {"ts": "2026-08-25T10:00:00", "speaker": "Alex", "text": "hallo",
         "agent": "ernaehrungsplaner", "remote_needed": 0}
    )
    r2 = store.record(
        {"ts": "2026-08-25T10:00:01", "speaker": "Sam", "text": "tschüss",
         "agent": "demo", "remote_needed": 1}
    )
    rows = store.recent(10)
    assert len(rows) == 2
    assert rows[0]["id"] == r2
    assert rows[0]["speaker"] == "Sam"
    assert rows[0]["text"] == "tschüss"
    assert rows[0]["agent"] == "demo"
    assert rows[0]["remote_needed"] == 1
    assert rows[1]["id"] == r1
    assert rows[1]["speaker"] == "Alex"
    assert rows[1]["text"] == "hallo"
    assert rows[1]["remote_needed"] == 0
    store.close()


def test_recent_limit(tmp_path):
    store = _store(tmp_path)
    for i in (1, 2, 3):
        store.record({"ts": str(i), "speaker": f"s{i}", "text": f"t{i}",
                      "agent": "demo", "remote_needed": 0})
    rows = store.recent(2)
    assert [r["text"] for r in rows] == ["t3", "t2"]
    store.close()


def test_since(tmp_path):
    store = _store(tmp_path)
    first = store.record({"ts": "1", "speaker": "s1", "text": "t1", "agent": "demo", "remote_needed": 0})
    store.record({"ts": "2", "speaker": "s2", "text": "t2", "agent": "demo", "remote_needed": 0})
    store.record({"ts": "3", "speaker": "s3", "text": "t3", "agent": "demo", "remote_needed": 0})
    rows = store.since(first)
    assert [r["text"] for r in rows] == ["t2", "t3"]
    store.close()


def test_missing_values_are_null(tmp_path):
    store = _store(tmp_path)
    store.record({"speaker": "Alex", "text": "hallo"})
    row = store.recent(1)[0]
    assert row["tokens_router"] is None
    assert row["tokens_agent"] is None
    assert row["tokens_remote"] is None
    assert row["latency_stt_ms"] is None
    assert row["latency_router_ms"] is None
    assert row["latency_agent_ms"] is None
    assert row["latency_tts_ms"] is None
    assert row["latency_total_ms"] is None
    store.close()


def test_max_rowid(tmp_path):
    store = _store(tmp_path)
    assert store.max_rowid() == 0
    store.record({"speaker": "Alex", "text": "hallo"})
    store.record({"speaker": "Sam", "text": "tschüss"})
    assert store.max_rowid() == 2
    store.close()
