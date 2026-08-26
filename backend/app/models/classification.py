from sqlalchemy import BigInteger, Column, Float, ForeignKey, Index, TIMESTAMP, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class Classification(Base):
    """
    LLM output for a post. One active row per post (UNIQUE on post_id).
    Re-classification replaces the existing row rather than inserting a new one.
    """

    __tablename__ = "classifications"
    __table_args__ = (
        UniqueConstraint("post_id"),
        Index("idx_classifications_category", "category"),
        Index("idx_classifications_region", "region"),
    )

    id = Column(BigInteger, primary_key=True)
    post_id = Column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)

    # LLM output fields
    category = Column(Text, nullable=False)          # 'infrastructure' | 'public_service' | 'corruption' | 'other'
    sentiment = Column(Text, nullable=False)          # 'negative' | 'neutral' | 'mixed'
    referenced_agency = Column(Text, nullable=True)  # e.g. 'PLN', 'Dinas Kependudukan'
    region = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)        # 0.0–1.0
    model_version = Column(Text, nullable=False)     # tracks prompt + model version used

    classified_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    post = relationship("Post", backref="classification")
