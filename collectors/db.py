"""SQLite 연결 / 스키마 초기화 / 수집 로그 헬퍼."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.executescript(schema)
        # === Migrations (ADD COLUMN if missing) ===
        cols = {r["name"] for r in
                conn.execute("PRAGMA table_info(recommendations)").fetchall()}
        if "rating_score" not in cols:
            conn.execute("ALTER TABLE recommendations "
                         "ADD COLUMN rating_score INTEGER")
        if "rating_breakdown_json" not in cols:
            conn.execute("ALTER TABLE recommendations "
                         "ADD COLUMN rating_breakdown_json TEXT")
        tcols = {r["name"] for r in
                 conn.execute("PRAGMA table_info(predicted_trends)").fetchall()}
        if "timeframe" not in tcols:
            conn.execute("ALTER TABLE predicted_trends "
                         "ADD COLUMN timeframe TEXT")
        conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start_log(source: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO collection_log (source, started_at) VALUES (?, ?)",
            (source, now_iso()),
        )
        conn.commit()
        return cur.lastrowid


def finish_log(log_id: int, rows_added: int, rows_updated: int = 0,
               error: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE collection_log
            SET finished_at = ?, rows_added = ?, rows_updated = ?, error = ?
            WHERE log_id = ?
            """,
            (now_iso(), rows_added, rows_updated, error, log_id),
        )
        conn.commit()
