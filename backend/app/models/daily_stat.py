from sqlalchemy import Column, Date, Float, Integer, PrimaryKeyConstraint, Text

from app.models.base import Base


class DailyStat(Base):
    """
    Precomputed daily aggregates for fast dashboard queries.

    Note: `region` is part of the composite primary key and therefore cannot
    be NULL in Postgres. An empty string ('') represents a rollup row
    that covers all regions for that date + category combination.
    """

    __tablename__ = "daily_stats"
    __table_args__ = (PrimaryKeyConstraint("stat_date", "category", "region"),)

    stat_date = Column(Date, nullable=False)
    category = Column(Text, nullable=False)
    region = Column(Text, nullable=False, default="")   # '' = all-regions aggregate
    post_count = Column(Integer, nullable=False)
    avg_sentiment_score = Column(Float, nullable=True)  # numeric encoding of sentiment, e.g. -1.0–1.0
