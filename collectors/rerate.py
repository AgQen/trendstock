"""모든 recommendations 의 grade 를 룰 기반(ratings.py)으로 재계산.

매일 가격 수집 후 실행해도 idempotent — 같은 날짜의 entry_close 는 안 바뀌고,
시간이 지나면서 모멘텀/타이밍 점수만 갱신됨. (다만 분석 당시의 등급을 보존하는 게
검증에 더 정확하므로, 일반적으로는 신규 분석 시점에만 재계산 권장.)
"""

from __future__ import annotations

import json
import time

import yfinance as yf

from .db import get_conn, init_db
from .ratings import compute_rating, yahoo_ticker

# yfinance .info 캐시 (한 회 호출 내에서 같은 티커 재조회 방지)
_INFO_CACHE: dict[str, dict] = {}


def _fetch_info(yf_tk: str) -> dict:
    if yf_tk in _INFO_CACHE:
        return _INFO_CACHE[yf_tk]
    try:
        info = yf.Ticker(yf_tk).info or {}
    except Exception as e:
        print(f"  [WARN] yfinance .info 실패 {yf_tk}: {type(e).__name__}: {e}")
        info = {}
    _INFO_CACHE[yf_tk] = info
    return info


def _prices_asc(conn, asset_id: int, base_date: str, n: int = 21) -> list[float]:
    rows = conn.execute(
        "SELECT close FROM price_history "
        "WHERE asset_id = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        (asset_id, base_date, n),
    ).fetchall()
    return [float(r["close"]) for r in reversed(rows)]


def rerate(date: str | None = None) -> None:
    """date 가 None 이면 모든 recommendations 대상."""
    init_db()

    with get_conn() as conn:
        if date:
            recs = conn.execute(
                "SELECT rec_id, asset_id, analysis_date "
                "FROM recommendations WHERE analysis_date = ? "
                "ORDER BY rec_id ASC",
                (date,),
            ).fetchall()
        else:
            recs = conn.execute(
                "SELECT rec_id, asset_id, analysis_date "
                "FROM recommendations ORDER BY rec_id ASC"
            ).fetchall()

        print(f"  대상 recommendations : {len(recs)}건")

        updated = 0
        upgraded = 0
        downgraded = 0

        for rec in recs:
            asset = conn.execute(
                "SELECT ticker, exchange, country, name "
                "FROM assets WHERE asset_id = ?",
                (rec["asset_id"],),
            ).fetchone()

            yf_tk = yahoo_ticker(asset["ticker"], asset["exchange"], asset["country"])
            info = _fetch_info(yf_tk)
            prices = _prices_asc(conn, rec["asset_id"], rec["analysis_date"], 21)

            rating = compute_rating(info, prices)

            # 기존 grade
            old_grade_row = conn.execute(
                "SELECT grade FROM recommendations WHERE rec_id = ?",
                (rec["rec_id"],),
            ).fetchone()
            old = old_grade_row["grade"] if old_grade_row else None
            new = rating["grade"]

            conn.execute(
                "UPDATE recommendations "
                "SET grade = ?, rating_score = ?, rating_breakdown_json = ? "
                "WHERE rec_id = ?",
                (new, rating["total"],
                 json.dumps(rating, ensure_ascii=False), rec["rec_id"]),
            )
            updated += 1

            order = ["Caution", "Hold", "Buy", "Strong Buy"]
            try:
                if order.index(new) > order.index(old):
                    upgraded += 1
                elif order.index(new) < order.index(old):
                    downgraded += 1
            except ValueError:
                pass

            sign = "↑" if new != old and order.index(new) > order.index(old or "Hold") \
                   else ("↓" if old and new != old else "·")
            name = (asset["name"] or "")[:12]
            print(f"  {sign} {asset['ticker']:<8} {name:<12} "
                  f"{(old or '-'):<11} → {new:<11} "
                  f"(총점 {rating['total']:+d}: 펀더 "
                  f"{rating['dimensions']['fundamentals']['score']:+d}, "
                  f"모멘텀 {rating['dimensions']['momentum']['score']:+d}, "
                  f"타이밍 {rating['dimensions']['timing']['score']:+d})")

            time.sleep(0.05)  # yfinance 정중함

        conn.commit()

    print(f"\n  [OK] 갱신 {updated}건  ↑{upgraded}  ↓{downgraded}")


def main() -> None:
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else None
    rerate(date)


if __name__ == "__main__":
    main()
