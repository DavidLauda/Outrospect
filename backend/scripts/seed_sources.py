"""
Seed a handful of example sources so ingestion has something to run against.

Usage (from backend/):
    python scripts/seed_sources.py

Requires DATABASE_URL in the environment (or a .env file in backend/).
"""

import sys
import os

# Allow running from any working directory as long as `backend/` is in the path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal
from app.models.source import Source


SEED_SOURCES = [
    {
        "platform": "twitter",
        "source_type": "hashtag",
        "value": "#layananpublik",
        "region_hint": None,
        "active": True,
    },
    {
        "platform": "twitter",
        "source_type": "keyword",
        "value": "keluhan infrastruktur",
        "region_hint": None,
        "active": True,
    },
    {
        "platform": "twitter",
        "source_type": "keyword",
        "value": "korupsi pemerintah daerah",
        "region_hint": None,
        "active": True,
    },
]


def main() -> None:
    db = SessionLocal()
    try:
        stmt = (
            insert(Source)
            .values(SEED_SOURCES)
            .on_conflict_do_nothing(index_elements=["platform", "source_type", "value"])
        )
        result = db.execute(stmt)
        db.commit()
        print(f"Inserted {result.rowcount} source(s) (duplicates skipped).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
