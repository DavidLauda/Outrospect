from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas import SpikeOut, TrendPoint
from app.db import get_db
from app.models.daily_stat import DailyStat
from app.services.aggregate import check_spikes

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/trend", response_model=list[TrendPoint])
def get_trend(
    category: Optional[str] = Query(None, description="Filter to a single category"),
    region: Optional[str] = Query(None, description="Filter to a single region; use '' for all-regions rollup"),
    days: int = Query(30, ge=1, le=365, description="How many trailing days to return"),
    db: Session = Depends(get_db),
) -> list[TrendPoint]:
    """
    Returns daily_stats rows for the requested window, newest first.
    Defaults to the all-regions rollup (region='') when no region filter is given,
    which is what the dashboard trend chart will use most of the time.
    """
    cutoff = date.today() - timedelta(days=days)

    q = db.query(DailyStat).filter(DailyStat.stat_date >= cutoff)

    if category:
        q = q.filter(DailyStat.category == category)

    # Default to the all-regions rollup so callers don't have to pass region=''
    if region is not None:
        q = q.filter(DailyStat.region == region)
    else:
        q = q.filter(DailyStat.region == "")

    rows = q.order_by(DailyStat.stat_date.desc()).all()

    return [
        TrendPoint(
            stat_date=r.stat_date,
            category=r.category,
            region=r.region,
            post_count=r.post_count,
            avg_sentiment_score=r.avg_sentiment_score,
        )
        for r in rows
    ]


@router.get("/spikes", response_model=list[SpikeOut])
def get_spikes() -> list[SpikeOut]:
    """
    Returns spike events for today: categories whose post count exceeds
    2.5x the 14-day trailing average.
    """
    events = check_spikes()
    return [
        SpikeOut(
            category=e.category,
            today_count=e.today_count,
            trailing_avg=e.trailing_avg,
            ratio=e.ratio,
        )
        for e in events
    ]
