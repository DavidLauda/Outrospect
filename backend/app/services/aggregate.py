"""
Aggregation service.

Computes and upserts daily_stats rows, then exposes a spike-detection
function for alerting.

Usage (manual run from backend/):
    python -m app.services.aggregate

Called by the APScheduler job in app/jobs/aggregate.py once wired up.

--- Sentiment encoding ---
Sentiment strings are mapped to a numeric score for averaging:

    negative = -1.0
    mixed    =  0.0
    neutral  =  1.0

This is a monotonic scale so the arithmetic mean is meaningful:
  -1.0  all posts are complaints
   0.0  equal mix, or all "mixed"
  +1.0  all posts are neutral / non-critical

Using neutral=1 (not 0) separates it from mixed in the average, which
matters when you want to distinguish "noisy-but-balanced" days from
"genuinely calm" days.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.classification import Classification
from app.models.daily_stat import DailyStat
from app.models.post import Post

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentiment encoding
# ---------------------------------------------------------------------------

_SENTIMENT_SCORE: dict[str, float] = {
    "negative": -1.0,
    "mixed": 0.0,
    "neutral": 1.0,
}


def _sentiment_case():
    """SQLAlchemy CASE expression that maps sentiment text to its numeric score."""
    return func.avg(
        func.cast(
            text(
                "CASE classification.sentiment"
                " WHEN 'negative' THEN -1.0"
                " WHEN 'mixed'    THEN  0.0"
                " WHEN 'neutral'  THEN  1.0"
                " ELSE 0.0 END"
            ),
            type_=func.Float(),
        )
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def run_aggregation(target_date: date | None = None) -> int:
    """
    Computes daily_stats for `target_date` (defaults to yesterday) and
    upserts the results.

    Returns the number of rows written.
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    db: Session = SessionLocal()
    try:
        rows = _compute_stats(db, target_date)
        if not rows:
            log.info("No classified posts found for %s — nothing to aggregate.", target_date)
            return 0

        _upsert_stats(db, rows)
        db.commit()
        log.info("Aggregated %d row(s) for %s.", len(rows), target_date)
        return len(rows)
    finally:
        db.close()


def _compute_stats(db: Session, target_date: date) -> list[dict]:
    """
    Returns a list of dicts ready for upsert, one per (category, region) pair
    that appears in classified posts on `target_date`.

    Also computes an all-regions rollup row (region='') for each category.
    """
    # Query classifications joined to posts, filtered to the target date.
    # posted_at is TIMESTAMPTZ; cast to DATE in the DB for grouping.
    q = (
        db.query(
            func.cast(Post.posted_at, type_=func.Date()).label("stat_date"),
            Classification.category,
            func.coalesce(Classification.region, "").label("region"),
            func.count(Post.id).label("post_count"),
        )
        .join(Classification, Post.id == Classification.post_id)
        .filter(
            func.cast(Post.posted_at, type_=func.Date()) == target_date
        )
        .group_by(
            func.cast(Post.posted_at, type_=func.Date()),
            Classification.category,
            func.coalesce(Classification.region, ""),
        )
    )

    per_region_rows = q.all()

    # --- Compute avg_sentiment_score separately so we keep the query simple ---
    # One additional query per (category, region) would be expensive; instead,
    # pull sentiment alongside count in a single query using a CASE average.
    sentiment_q = (
        db.query(
            Classification.category,
            func.coalesce(Classification.region, "").label("region"),
            func.avg(
                func.cast(
                    func.case(
                        (Classification.sentiment == "negative", -1.0),
                        (Classification.sentiment == "mixed", 0.0),
                        (Classification.sentiment == "neutral", 1.0),
                        else_=0.0,
                    ),
                    type_=None,   # let SQLAlchemy infer FLOAT
                )
            ).label("avg_score"),
        )
        .join(Post, Post.id == Classification.post_id)
        .filter(
            func.cast(Post.posted_at, type_=func.Date()) == target_date
        )
        .group_by(
            Classification.category,
            func.coalesce(Classification.region, ""),
        )
    )

    # Build a lookup: (category, region) -> avg_score
    sentiment_lookup: dict[tuple[str, str], float | None] = {
        (row.category, row.region): row.avg_score
        for row in sentiment_q.all()
    }

    rows = []
    # Per-region rows
    for r in per_region_rows:
        rows.append(
            {
                "stat_date": target_date,
                "category": r.category,
                "region": r.region,
                "post_count": r.post_count,
                "avg_sentiment_score": sentiment_lookup.get((r.category, r.region)),
            }
        )

    # All-regions rollup: one row per category with region=''
    rollup_q = (
        db.query(
            Classification.category,
            func.count(Post.id).label("post_count"),
            func.avg(
                func.cast(
                    func.case(
                        (Classification.sentiment == "negative", -1.0),
                        (Classification.sentiment == "mixed", 0.0),
                        (Classification.sentiment == "neutral", 1.0),
                        else_=0.0,
                    ),
                    type_=None,
                )
            ).label("avg_score"),
        )
        .join(Post, Post.id == Classification.post_id)
        .filter(
            func.cast(Post.posted_at, type_=func.Date()) == target_date
        )
        .group_by(Classification.category)
    )

    for r in rollup_q.all():
        # Only add the rollup row if it differs from per-region (i.e., there
        # are multiple regions — if region was always '', the per-region row
        # already is the rollup).
        already_have_rollup = any(
            row["category"] == r.category and row["region"] == ""
            for row in rows
        )
        if not already_have_rollup:
            rows.append(
                {
                    "stat_date": target_date,
                    "category": r.category,
                    "region": "",
                    "post_count": r.post_count,
                    "avg_sentiment_score": r.avg_score,
                }
            )

    return rows


def _upsert_stats(db: Session, rows: list[dict]) -> None:
    """
    Upserts rows into daily_stats using ON CONFLICT DO UPDATE.
    Re-running aggregation for the same date overwrites with fresh counts.
    """
    stmt = (
        pg_insert(DailyStat)
        .values(rows)
        .on_conflict_do_update(
            index_elements=["stat_date", "category", "region"],
            set_={
                "post_count": pg_insert(DailyStat).excluded.post_count,
                "avg_sentiment_score": pg_insert(DailyStat).excluded.avg_sentiment_score,
            },
        )
    )
    db.execute(stmt)


# ---------------------------------------------------------------------------
# Spike detection
# ---------------------------------------------------------------------------

@dataclass
class SpikeEvent:
    category: str
    today_count: int
    trailing_avg: float
    ratio: float


_SPIKE_THRESHOLD = 2.5
_TRAILING_DAYS = 14


def check_spikes(reference_date: date | None = None) -> list[SpikeEvent]:
    """
    Compares today's (or `reference_date`'s) all-regions post counts against
    each category's trailing 14-day average (excluding `reference_date` itself).

    Returns a list of SpikeEvent for any category where:
        today_count > trailing_avg * 2.5

    An empty trailing average (no history yet) is skipped — we can't
    meaningfully detect a spike with no baseline.
    """
    if reference_date is None:
        reference_date = date.today()

    window_start = reference_date - timedelta(days=_TRAILING_DAYS)
    window_end = reference_date - timedelta(days=1)

    db: Session = SessionLocal()
    try:
        # Today's counts (all-regions rollup rows only)
        today_rows = (
            db.query(DailyStat.category, DailyStat.post_count)
            .filter(
                DailyStat.stat_date == reference_date,
                DailyStat.region == "",
            )
            .all()
        )

        if not today_rows:
            log.info("No daily_stats for %s — nothing to spike-check.", reference_date)
            return []

        # Trailing averages for each category
        trailing = (
            db.query(
                DailyStat.category,
                func.avg(DailyStat.post_count).label("avg_count"),
            )
            .filter(
                DailyStat.stat_date >= window_start,
                DailyStat.stat_date <= window_end,
                DailyStat.region == "",
            )
            .group_by(DailyStat.category)
            .all()
        )

        trailing_by_category: dict[str, float] = {
            row.category: float(row.avg_count) for row in trailing
        }

        spikes: list[SpikeEvent] = []
        for row in today_rows:
            avg = trailing_by_category.get(row.category)
            if avg is None or avg == 0:
                # No baseline — skip rather than dividing by zero
                continue
            ratio = row.post_count / avg
            if ratio > _SPIKE_THRESHOLD:
                spikes.append(
                    SpikeEvent(
                        category=row.category,
                        today_count=row.post_count,
                        trailing_avg=round(avg, 1),
                        ratio=round(ratio, 2),
                    )
                )

        return spikes
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )

    written = run_aggregation()
    print(f"\nAggregation: {written} row(s) written for {date.today() - timedelta(days=1)}.")

    spikes = check_spikes()
    if spikes:
        print(f"\n{'SPIKE ALERT':=^50}")
        for s in spikes:
            print(
                f"  {s.category:<20}  today={s.today_count:>4}  "
                f"14d_avg={s.trailing_avg:>6.1f}  ratio={s.ratio:.2f}x"
            )
    else:
        print("\nNo spikes detected.")
