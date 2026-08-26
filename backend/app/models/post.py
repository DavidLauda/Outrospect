from sqlalchemy import BigInteger, Column, Index, TIMESTAMP, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base


class Post(Base):
    """
    Raw scraped posts. Original content is never overwritten; classification
    lives in the separate `classifications` table.
    """

    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("source_platform", "source_post_id"),
        Index("idx_posts_posted_at", "posted_at"),
    )

    id = Column(BigInteger, primary_key=True)
    source_platform = Column(Text, nullable=False)
    source_post_id = Column(Text, nullable=False)   # platform's native tweet/post ID
    author_handle = Column(Text, nullable=True)     # public handle only; no profile metadata stored
    content_text = Column(Text, nullable=False)
    posted_at = Column(TIMESTAMP(timezone=True), nullable=False)
    scraped_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default="now()")
    url = Column(Text, nullable=True)
    engagement = Column(JSONB, nullable=True)       # {"likes": 12, "reposts": 3, "replies": 5}
    raw_metadata = Column(JSONB, nullable=True)     # retained for future reprocessing
