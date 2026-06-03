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


DEFAULT_WEIGHTS: dict = {
    "fund_weight":     0.9,   # 재무 (후행 6개월, 중요하지만 비중 일부 감소)
    "momentum_weight": 0.6,   # 모멘텀 (이미 벌어진 사실 → 후행)
    "timing_weight":   1.0,   # 타이밍 (진입 시점 선행)
    "volume_weight":   1.0,   # 거래량 (수급 선행)
    "rs_weight":       1.2,   # 상대강도: SPY 대비 초과수익 (선행, 핵심)
    "risk_weight":     0.8,   # 위험도/MDD (낙폭 관리)
}


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
        if "detail_json" not in cols:
            conn.execute("ALTER TABLE recommendations "
                         "ADD COLUMN detail_json TEXT")
        tcols = {r["name"] for r in
                 conn.execute("PRAGMA table_info(predicted_trends)").fetchall()}
        if "timeframe" not in tcols:
            conn.execute("ALTER TABLE predicted_trends "
                         "ADD COLUMN timeframe TEXT")
        # rule_weights 컬럼 마이그레이션 (rs_weight, risk_weight 추가)
        wcols = {r["name"] for r in
                 conn.execute("PRAGMA table_info(rule_weights)").fetchall()}
        if "rs_weight" not in wcols:
            conn.execute("ALTER TABLE rule_weights ADD COLUMN rs_weight REAL NOT NULL DEFAULT 1.2")
        if "risk_weight" not in wcols:
            conn.execute("ALTER TABLE rule_weights ADD COLUMN risk_weight REAL NOT NULL DEFAULT 0.8")

        # Seed default weights if table is empty
        n = conn.execute("SELECT COUNT(*) FROM rule_weights").fetchone()[0]
        if n == 0:
            conn.execute(
                "INSERT INTO rule_weights "
                "(effective_date, fund_weight, momentum_weight, timing_weight, volume_weight, rs_weight, risk_weight, note, created_at) "
                "VALUES (date('now'), ?, ?, ?, ?, ?, ?, ?, ?)",
                (DEFAULT_WEIGHTS["fund_weight"], DEFAULT_WEIGHTS["momentum_weight"],
                 DEFAULT_WEIGHTS["timing_weight"], DEFAULT_WEIGHTS["volume_weight"],
                 DEFAULT_WEIGHTS["rs_weight"], DEFAULT_WEIGHTS["risk_weight"],
                 "초기 설정 v2 — RS(상대강도)·위험도(MDD) 차원 추가", now_iso()),
            )
        conn.commit()


def load_weights(conn=None) -> dict:
    """최신 활성 가중치 반환. conn 없으면 새 연결."""
    close = conn is None
    if close:
        conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM rule_weights ORDER BY effective_date DESC LIMIT 1"
        ).fetchone()
        if not row:
            return DEFAULT_WEIGHTS.copy()
        result = {}
        for k in DEFAULT_WEIGHTS:
            try:
                result[k] = row[k]
            except (IndexError, KeyError):
                result[k] = DEFAULT_WEIGHTS[k]
        return result
    finally:
        if close:
            conn.close()


def weight_history(conn=None) -> list[dict]:
    """전체 가중치 변경 이력 (최신 순)."""
    close = conn is None
    if close:
        conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM rule_weights ORDER BY effective_date DESC LIMIT 24"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if close:
            conn.close()


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
