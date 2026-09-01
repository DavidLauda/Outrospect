from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import SourceCreate, SourceOut, SourcePatch
from app.db import get_db
from app.models.source import Source

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[SourceOut]:
    return db.query(Source).order_by(Source.id).all()


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def create_source(body: SourceCreate, db: Session = Depends(get_db)) -> SourceOut:
    """
    Adds a new scraping source. Returns 409 if the (platform, source_type, value)
    triple already exists.
    """
    source = Source(
        platform=body.platform,
        source_type=body.source_type,
        value=body.value,
        region_hint=body.region_hint,
        active=True,
    )
    db.add(source)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A source with this platform/source_type/value already exists.",
        )
    db.refresh(source)
    return source


@router.patch("/{source_id}", response_model=SourceOut)
def toggle_source(
    source_id: int, body: SourcePatch, db: Session = Depends(get_db)
) -> SourceOut:
    """Enables or disables a source without deleting it."""
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")
    source.active = body.active
    db.commit()
    db.refresh(source)
    return source
