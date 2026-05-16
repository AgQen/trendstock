"""yfinance: 활성 미국 종목의 최근 30일 OHLCV upsert."""

import time

import yfinance as yf

from .db import finish_log, get_conn, init_db, start_log


def collect() -> None:
    init_db()
    with get_conn() as conn:
        assets = conn.execute(
            "SELECT asset_id, ticker FROM assets "
            "WHERE country = 'US' AND is_active = 1 ORDER BY ticker"
        ).fetchall()

    log_id = start_log("yfinance_us")
    total = 0
    failed: list[str] = []

    for a in assets:
        try:
            hist = yf.Ticker(a["ticker"]).history(period="30d", auto_adjust=False)
            if hist.empty:
                failed.append(a["ticker"])
                print(f"  [WARN] {a['ticker']:<6} 빈 데이터")
                continue

            rows = [
                (
                    a["asset_id"],
                    idx.strftime("%Y-%m-%d"),
                    float(row["Open"]) if row["Open"] == row["Open"] else None,
                    float(row["High"]) if row["High"] == row["High"] else None,
                    float(row["Low"]) if row["Low"] == row["Low"] else None,
                    float(row["Close"]) if row["Close"] == row["Close"] else None,
                    float(row["Volume"]) if row["Volume"] == row["Volume"] else 0.0,
                )
                for idx, row in hist.iterrows()
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
            print(f"  [OK]   {a['ticker']:<6} rows={len(rows)}")
            time.sleep(0.25)  # rate-limit politeness

        except Exception as e:
            failed.append(a["ticker"])
            print(f"  [FAIL] {a['ticker']:<6} {type(e).__name__}: {e}")

    finish_log(
        log_id,
        rows_added=total,
        rows_updated=0,
        error=",".join(failed) if failed else None,
    )
    print(f"  ---- US 합계: {total} rows  실패 {len(failed)}건 ----")


if __name__ == "__main__":
    collect()
