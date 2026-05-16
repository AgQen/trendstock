"""seeds/assets.json -> assets 테이블 upsert."""

import json
from pathlib import Path

from .db import get_conn, init_db

SEED_PATH = Path(__file__).resolve().parent.parent / "seeds" / "assets.json"


def seed() -> None:
    init_db()
    assets = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    inserted, updated = 0, 0

    with get_conn() as conn:
        for a in assets:
            row = conn.execute(
                "SELECT asset_id FROM assets WHERE ticker = ? AND exchange = ?",
                (a["ticker"], a["exchange"]),
            ).fetchone()

            if row:
                conn.execute(
                    """
                    UPDATE assets
                    SET name = ?, country = ?, currency = ?,
                        sector = ?, industry = ?, is_active = 1
                    WHERE asset_id = ?
                    """,
                    (a["name"], a["country"], a["currency"],
                     a.get("sector"), a.get("industry"), row["asset_id"]),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO assets
                        (ticker, name, exchange, country, asset_class,
                         industry, sector, currency, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (a["ticker"], a["name"], a["exchange"], a["country"],
                     a.get("asset_class", "stock"),
                     a.get("industry"), a.get("sector"), a["currency"]),
                )
                inserted += 1
        conn.commit()

    print(f"  [OK]   inserted={inserted}  updated={updated}  total={inserted + updated}")


if __name__ == "__main__":
    seed()
