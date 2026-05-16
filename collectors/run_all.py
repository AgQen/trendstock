"""W1 일괄 실행: init -> seed -> US -> KR."""

from .collect_kr import collect as collect_kr
from .collect_us import collect as collect_us
from .db import get_conn, init_db
from .seed_assets import seed


def main() -> None:
    print("=" * 64)
    print(" TrendStock W1 — 데이터 수집 파이프라인")
    print("=" * 64)

    print("\n[1/4] DB 초기화")
    init_db()
    print("  [OK]")

    print("\n[2/4] assets 시드")
    seed()

    print("\n[3/4] 미국 주식 (yfinance)")
    collect_us()

    print("\n[4/4] 한국 주식 (pykrx)")
    collect_kr()

    print("\n" + "=" * 64)
    with get_conn() as conn:
        n_assets = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE is_active = 1"
        ).fetchone()[0]
        n_prices = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        latest = conn.execute("SELECT MAX(date) FROM price_history").fetchone()[0]

    print(f"  active assets       : {n_assets:>6}")
    print(f"  price_history rows  : {n_prices:>6}")
    print(f"  최신 가격 일자      : {latest}")
    print("=" * 64)
    print(" 완료. 다음:  python -m collectors.query")


if __name__ == "__main__":
    main()
