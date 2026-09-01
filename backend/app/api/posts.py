from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import PostOut, PostPage, ClassificationOut
from app.db import get_db
from app.models.classification import Classification
from app.models.post import Post

router = APIRouter(prefix="/posts", tags=["posts"])


def _classification_out(c: Classification | None) -> ClassificationOut | None:
    if c is None:
        return None
    return ClassificationOut(
        category=c.category,
        sentiment=c.sentiment,
        referenced_agency=c.referenced_agency,
        region=c.region,
        confidence=c.confidence,
        model_version=c.model_version,
        classified_at=c.classified_at,
    )


def _post_out(p: Post) -> PostOut:
    # Access the backref set up in Classification.post
    classification = getattr(p, "classification", None)
    # backref returns a list; grab first element if populated
    if isinstance(classification, list):
        classification = classification[0] if classification else None
    return PostOut(
        id=p.id,
        source_platform=p.source_platform,
        source_post_id=p.source_post_id,
        author_handle=p.author_handle,
        content_text=p.content_text,
        posted_at=p.posted_at,
        url=p.url,
        engagement=p.engagement,
        classification=_classification_out(classification),
    )


@router.get("", response_model=PostPage)
def list_posts(
    category: Optional[str] = Query(None, description="Filter by classification category"),
    region: Optional[str] = Query(None, description="Filter by classification region"),
    sentiment: Optional[str] = Query(None, description="Filter by sentiment"),
    date_from: Optional[date] = Query(None, description="Include posts on or after this date"),
    date_to: Optional[date] = Query(None, description="Include posts on or before this date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PostPage:
    q = db.query(Post).outerjoin(Classification, Post.id == Classification.post_id)

    if category:
        q = q.filter(Classification.category == category)
    if region:
        q = q.filter(Classification.region == region)
    if sentiment:
        q = q.filter(Classification.sentiment == sentiment)
    if date_from:
        q = q.filter(Post.posted_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(Post.posted_at <= datetime.combine(date_to, datetime.max.time()))

    total = q.count()
    posts = (
        q.order_by(Post.posted_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PostPage(
        total=total,
        page=page,
        page_size=page_size,
        items=[_post_out(p) for p in posts],
    )
