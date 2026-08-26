from sqlalchemy import Boolean, Column, Integer, Text, UniqueConstraint
from sqlalchemy import TIMESTAMP

from app.models.base import Base


class Source(Base):
    """
    Tracks what Outrospect is scraping: hashtags, keywords, or specific
    accounts (including regional autobase relay accounts).
    """

    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("platform", "source_type", "value"),)

    id = Column(Integer, primary_key=True)
    platform = Column(Text, nullable=False)        # 'twitter', 'facebook', etc.
    source_type = Column(Text, nullable=False)      # 'hashtag', 'keyword', 'account'
    value = Column(Text, nullable=False)            # the actual hashtag / keyword / handle
    region_hint = Column(Text, nullable=True)       # pre-tag region for region-specific sources
    active = Column(Boolean, nullable=False, default=True)
    last_scraped_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default="now()")
