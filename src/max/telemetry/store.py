"""Telemetrie-Store: persistiert Anfragen in SQLite (data/telemetry.db).

Eine Zeile pro Anfrage. Fehlende Werte bleiben NULL.
"""
import datetime
import os
import sqlite3

COLUMNS = (
    "ts", "speaker", "text", "agent", "remote_needed",
    "tokens_router", "tokens_agent", "tokens_remote",
    "latency_stt_ms", "latency_router_ms",
    "latency_agent_ms", "latency_tts_ms", "latency_remote_ms", "latency_total_ms",
)


class TelemetryStore:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # check_same_thread=False: Pipeline- und Dashboard-Thread teilen sich die Verbindung
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS requests ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "ts TEXT, speaker TEXT, text TEXT, agent TEXT,"
            "remote_needed INTEGER,"
            "tokens_router INTEGER, tokens_agent INTEGER, tokens_remote INTEGER,"
            "latency_stt_ms REAL, latency_router_ms REAL,"
            "latency_agent_ms REAL, latency_tts_ms REAL, latency_remote_ms REAL,"
            "latency_total_ms REAL)"
        )
        # Bestehende DBs: Spalte fehlertolerant nachlegen
        try:
            self._conn.execute("ALTER TABLE requests ADD COLUMN latency_remote_ms REAL")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        self._conn.commit()

    def record(self, req: dict) -> int:
        """Schreibt eine Zeile. Fehlende Keys werden NULL gespeichert. Liefert die id."""
        values = tuple(req.get(col) for col in COLUMNS)
        cur = self._conn.execute(
            "INSERT INTO requests (ts, speaker, text, agent, remote_needed,"
            "tokens_router, tokens_agent, tokens_remote,"
            "latency_stt_ms, latency_router_ms, latency_agent_ms,"
            "latency_tts_ms, latency_remote_ms, latency_total_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )
        self._conn.commit()
        return cur.lastrowid

    def _rows(self, sql: str, args) -> list[dict]:
        cur = self._conn.execute(sql, args)
        return [dict(zip(("id",) + COLUMNS, row)) for row in cur.fetchall()]

    def recent(self, limit: int = 50) -> list[dict]:
        """Die letzten limit Zeilen, neueste zuerst."""
        return self._rows("SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,))

    def since(self, rowid: int, limit: int = 100) -> list[dict]:
        """Alle Zeilen mit id > rowid, aufsteigend."""
        return self._rows("SELECT * FROM requests WHERE id > ? ORDER BY id LIMIT ?", (rowid, limit))

    def max_rowid(self) -> int:
        cur = self._conn.execute("SELECT COALESCE(MAX(id), 0) FROM requests")
        return cur.fetchone()[0]

    def close(self):
        self._conn.close()
