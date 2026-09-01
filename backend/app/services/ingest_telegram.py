"""
Telegram ingestion service.

Reads active rows from `sources` where platform = 'telegram', fetches new
messages for each channel via the MTProto API (Telethon, personal account),
and upserts them into `posts` using ON CONFLICT DO NOTHING.

Requires a session string generated once via scripts/telegram_login.py.

Usage (manual run from backend/):
    python -m app.services.ingest_telegram [--limit N]

Called by the APScheduler job in app/jobs/ingest.py once wired up.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import text
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from app.config import settings
from app.db import SessionLocal
from app.models.source import Source

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Telethon client factory
# ---------------------------------------------------------------------------


def _make_client() -> TelegramClient:
    """Builds a TelegramClient from the session string stored in env."""
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise RuntimeError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in the environment."
        )
    if not settings.telegram_session_string:
        raise RuntimeError(
            "TELEGRAM_SESSION_STRING is not set. "
            "Run scripts/telegram_login.py once to generate it."
        )
    return TelegramClient(
        StringSession(settings.telegram_session_string),
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
    )


# ---------------------------------------------------------------------------
# Per-source helpers
# ---------------------------------------------------------------------------


def _max_stored_id(db, channel: str) -> int:
    """
    Returns the highest Telegram message ID we already have for `channel`,
    or 0 if this channel has never been ingested.

    source_post_id is stored as "{channel}_{message_id}", so we extract the
    numeric suffix and take the max.
    """
    prefix = f"{channel}_"
    result = db.execute(
        text(
            """
            SELECT COALESCE(
                MAX(
                    CAST(
                        SUBSTRING(source_post_id FROM :prefix_len)
                        AS BIGINT
                    )
                ),
                0
            )
            FROM posts
            WHERE source_platform = 'telegram'
              AND source_post_id LIKE :pattern
            """
        ),
        {"prefix_len": len(prefix) + 1, "pattern": f"{prefix}%"},
    ).scalar()
    return int(result or 0)


def _build_post(channel: str, message) -> dict:
    """
    Maps a Telethon Message object to the kwargs expected by the Post model.
    """
    engagement = {}
    if message.views is not None:
        engagement["views"] = message.views
    if message.forwards is not None:
        engagement["forwards"] = message.forwards

    return dict(
        source_platform="telegram",
        source_post_id=f"{channel}_{message.id}",
        author_handle=channel,
        content_text=message.text or "",
        posted_at=message.date,
        url=f"https://t.me/{channel}/{message.id}",
        engagement=engagement or None,
        raw_metadata={
            "message_id": message.id,
            "views": message.views,
            "forwards": message.forwards,
            "edit_date": message.edit_date.isoformat() if message.edit_date else None,
        },
    )


# ---------------------------------------------------------------------------
# Core ingestion logic
# ---------------------------------------------------------------------------


async def _ingest_source(
    client: TelegramClient, db, source: Source, per_channel_limit: int
) -> int:
    """
    Fetches new messages for a single Telegram channel source and inserts them.
    Returns the count of messages inserted.
    """
    channel = source.value  # e.g. "infobandung"
    min_id = _max_stored_id(db, channel)

    log.info("Channel @%s — fetching messages with min_id=%d", channel, min_id)

    inserted = 0
    try:
        async for message in client.iter_messages(
            channel,
            limit=per_channel_limit,
            min_id=min_id,
            reverse=True,  # oldest-first so IDs are monotonically increasing on insert
        ):
            if not message.text:
                # Skip media-only, polls, etc. — no text to classify.
                continue

            post_kwargs = _build_post(channel, message)

            # ON CONFLICT DO NOTHING: if the row already exists (e.g. a
            # re-run after a partial failure), skip it silently.
            db.execute(
                text(
                    """
                    INSERT INTO posts
                        (source_platform, source_post_id, author_handle,
                         content_text, posted_at, url, engagement, raw_metadata)
                    VALUES
                        (:source_platform, :source_post_id, :author_handle,
                         :content_text, :posted_at, :url,
                         :engagement::jsonb, :raw_metadata::jsonb)
                    ON CONFLICT (source_platform, source_post_id) DO NOTHING
                    """
                ),
                {
                    **post_kwargs,
                    "engagement": (
                        None
                        if post_kwargs["engagement"] is None
                        else json.dumps(post_kwargs["engagement"])
                    ),
                    "raw_metadata": json.dumps(post_kwargs["raw_metadata"]),
                },
            )
            inserted += 1

    except FloodWaitError as exc:
        wait = exc.seconds
        log.warning(
            "FloodWaitError for @%s — Telegram says wait %ds. Sleeping.", channel, wait
        )
        await asyncio.sleep(wait)
        # Do not re-raise; the next scheduled run will pick up where we left off.

    db.commit()
    log.info("Channel @%s — inserted %d new post(s).", channel, inserted)
    return inserted


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_ingestion(per_channel_limit: int = 200) -> None:
    """
    Main ingestion coroutine. Reads all active Telegram sources and fetches
    new messages for each one.
    """
    db = SessionLocal()
    try:
        sources = (
            db.query(Source)
            .filter(
                Source.platform == "telegram",
                Source.source_type == "channel",
                Source.active.is_(True),
            )
            .all()
        )

        if not sources:
            log.info("No active Telegram channel sources found. Nothing to do.")
            return

        log.info("Found %d active Telegram source(s).", len(sources))

        client = _make_client()
        async with client:
            for source in sources:
                try:
                    await _ingest_source(client, db, source, per_channel_limit)
                except Exception:
                    # Log and continue to the next source rather than aborting
                    # the whole run for one bad channel.
                    log.exception(
                        "Unhandled error ingesting @%s — skipping.", source.value
                    )
                finally:
                    # Update last_scraped_at regardless of whether messages
                    # were found, so we have a reliable "last attempted" timestamp.
                    source.last_scraped_at = datetime.now(tz=timezone.utc)
                    db.commit()

    finally:
        db.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(
        description="Ingest new messages from active Telegram channel sources."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        metavar="N",
        help=(
            "Maximum messages to fetch per channel per run (default: 200). "
            "Only messages newer than the last stored ID are fetched."
        ),
    )
    args = parser.parse_args()

    asyncio.run(run_ingestion(per_channel_limit=args.limit))
