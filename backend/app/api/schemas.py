"""
Pydantic response and request schemas shared across route modules.
Kept in one file so changes to a field shape are visible in one place.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    source_type: str
    value: str
    region_hint: Optional[str]
    active: bool
    last_scraped_at: Optional[datetime]
    created_at: datetime


class SourceCreate(BaseModel):
    platform: str
    source_type: str
    value: str
    region_hint: Optional[str] = None


class SourcePatch(BaseModel):
    active: bool


# ---------------------------------------------------------------------------
# Posts (joined with classification)
# ---------------------------------------------------------------------------

class ClassificationOut(BaseModel):
    category: str
    sentiment: str
    referenced_agency: Optional[str]
    region: Optional[str]
    confidence: Optional[float]
    model_version: str
    classified_at: datetime


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_platform: str
    source_post_id: str
    author_handle: Optional[str]
    content_text: str
    posted_at: datetime
    url: Optional[str]
    engagement: Optional[dict]
    classification: Optional[ClassificationOut] = None


class PostPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[PostOut]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TrendPoint(BaseModel):
    stat_date: date
    category: str
    region: str
    post_count: int
    avg_sentiment_score: Optional[float]


class SpikeOut(BaseModel):
    category: str
    today_count: int
    trailing_avg: float
    ratio: float
