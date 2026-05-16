"""pykrx: 활성 한국 종목의 최근 영업일 OHLCV upsert."""

import time
from datetime import date, timedelta

from pykrx import stock as krx

from .db import finish_log, get_conn, init_db, start_log


def collect() -> None:
    init_db()
    with get_conn() as conn:
        assets = conn.execute(
            "SELECT asset_id, ticker FROM assets "
            "WHERE country = 'KR' AND is_active = 1 ORDER BY ticker"
        ).fetchall()

    log_id = start_log("pykrx_kr")
    total = 0
    failed: list[str] = []

    today = date.today()
    start = today - timedelta(days=45)
    s_str = start.strftime("%Y%m%d")
    e_str = today.strftime("%Y%m%d")

    for a in assets:
        try:
            df = krx.get_market_ohlcv(s_str, e_str, a["ticker"])
            if df.empty:
                failed.append(a["ticker"])
                print(f"  [WARN] {a['ticker']:<8} 빈 데이터")
                continue

            rows = [
                (
                    a["asset_id"],
                    idx.strftime("%Y-%m-%d"),
                    float(row["시가"]),
                    float(row["고가"]),
                    float(row["저가"]),
                    float(row["종가"]),
                    float(row["거래량"]),
                )
                for idx, row in df.iterrows()
            ]

            with get_conn() as conn:
                conn.executemany(
                    """
                    INSERT INTO price_history
                        (asset_id, date, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id, date) DO UPDATE SET
                        open   = excluded.open,
                        high   = excluded.high,
                        low    = excluded.low,
                        close  = excluded.close,
                        volume = excluded.volume
                    """,
                    rows,
                )
                conn.commit()

            total += len(rows)
            print(f"  [OK]   {a['ticker']:<8} rows={len(rows)}")
            time.sleep(0.25)

        except Exception as e:
            failed.append(a["ticker"])
            print(f"  [FAIL] {a['ticker']:<8} {type(e).__name__}: {e}")

    finish_log(
        log_id,
        rows_added=total,
        rows_updated=0,
        error=",".join(failed) if failed else None,
    )
    print(f"  ---- KR 합계: {total} rows  실패 {len(failed)}건 ----")


if __name__ == "__main__":
    collect()
