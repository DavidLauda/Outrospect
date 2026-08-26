"""
Twitter/X ingestion service.

Pulls tweets for every active Twitter source and upserts them into `posts`.

Usage (manual run from backend/):
    python -m app.services.ingest_twitter

Called by the APScheduler job in app/jobs/ingest.py once wired up.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models.post import Post
from app.models.source import Source

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# X API v2 constants
# ---------------------------------------------------------------------------

BASE_URL = "https://api.twitter.com/2"

# Fields requested for every tweet object.
TWEET_FIELDS = "id,text,author_id,created_at,public_metrics,entities"

# Expansions so the response includes the author username in includes.users.
EXPANSIONS = "author_id"
USER_FIELDS = "username"

# Tweets returned per page (API max for recent search and user timeline).
MAX_RESULTS = 100

# ---------------------------------------------------------------------------
# Rate-limit retry
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_BASE_WAIT = 60  # seconds; doubled on each retry


def _request_with_backoff(client: httpx.Client, url: str, params: dict) -> dict:
    """
    GET `url` with `params`, retrying on 429 with exponential backoff.
    Raises on non-retryable errors.
    """
    wait = _RETRY_BASE_WAIT
    for attempt in range(1, _MAX_RETRIES + 1):
        response = client.get(url, params=params)

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429:
            # Prefer the Retry-After header when present.
            retry_after = response.headers.get("retry-after")
            sleep_for = int(retry_after) if retry_after else wait
            log.warning(
                "Rate limited by X API (attempt %d/%d). Waiting %ds.",
                attempt,
                _MAX_RETRIES,
                sleep_for,
            )
            time.sleep(sleep_for)
            wait *= 2
            continue

        # Any other non-2xx is a real error; surface it.
        response.raise_for_status()

    raise RuntimeError(f"X API rate limit not resolved after {_MAX_RETRIES} retries.")


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

def _build_author_map(payload: dict) -> dict[str, str]:
    """
    Returns {author_id: username} from the includes.users expansion.
    Falls back to an empty dict if the expansion is absent.
    """
    users = payload.get("includes", {}).get("users", [])
    return {u["id"]: u["username"] for u in users}


def _tweet_to_row(tweet: dict, author_map: dict[str, str]) -> dict[str, Any]:
    """
    Maps a raw X API tweet object to the shape expected by the `posts` table.
    """
    author_id = tweet.get("author_id", "")
    handle = author_map.get(author_id)

    metrics = tweet.get("public_metrics", {})
    engagement = {
        "likes": metrics.get("like_count", 0),
        "reposts": metrics.get("retweet_count", 0),
        "replies": metrics.get("reply_count", 0),
    }

    tweet_id = tweet["id"]
    return {
        "source_platform": "twitter",
        "source_post_id": tweet_id,
        "author_handle": handle,
        "content_text": tweet["text"],
        "posted_at": datetime.fromisoformat(
            tweet["created_at"].replace("Z", "+00:00")
        ),
        "url": f"https://twitter.com/i/web/status/{tweet_id}",
        "engagement": engagement,
        "raw_metadata": tweet,  # full object kept for reprocessing
    }


# ---------------------------------------------------------------------------
# Per-source fetch strategies
# ---------------------------------------------------------------------------

def _fetch_recent_search(
    client: httpx.Client, query: str
) -> list[dict]:
    """
    Fetches up to one page of results from GET /2/tweets/search/recent.
    Returns a list of raw tweet objects with author_handle already resolved.
    """
    params = {
        "query": query,
        "max_results": MAX_RESULTS,
        "tweet.fields": TWEET_FIELDS,
        "expansions": EXPANSIONS,
        "user.fields": USER_FIELDS,
    }
    payload = _request_with_backoff(client, f"{BASE_URL}/tweets/search/recent", params)
    tweets = payload.get("data", [])
    author_map = _build_author_map(payload)
    return [_tweet_to_row(t, author_map) for t in tweets]


def _resolve_user_id(client: httpx.Client, username: str) -> str:
    """
    Looks up the numeric user ID for a given username.
    Strips a leading '@' if present.
    """
    handle = username.lstrip("@")
    payload = _request_with_backoff(
        client, f"{BASE_URL}/users/by/username/{handle}", params={}
    )
    return payload["data"]["id"]


def _fetch_user_timeline(
    client: httpx.Client, username: str
) -> list[dict]:
    """
    Fetches up to one page of tweets from GET /2/users/:id/tweets.
    Returns a list of row dicts ready for insertion.
    """
    user_id = _resolve_user_id(client, username)
    params = {
        "max_results": MAX_RESULTS,
        "tweet.fields": TWEET_FIELDS,
        "expansions": EXPANSIONS,
        "user.fields": USER_FIELDS,
    }
    payload = _request_with_backoff(
        client, f"{BASE_URL}/users/{user_id}/tweets", params
    )
    tweets = payload.get("data", [])
    author_map = _build_author_map(payload)
    return [_tweet_to_row(t, author_map) for t in tweets]


# ---------------------------------------------------------------------------
# Insertion
# ---------------------------------------------------------------------------

def _insert_posts(db: Session, rows: list[dict]) -> int:
    """
    Bulk-inserts rows into `posts` with ON CONFLICT DO NOTHING.
    Returns the number of newly inserted rows.
    """
    if not rows:
        return 0
    stmt = pg_insert(Post).values(rows).on_conflict_do_nothing(
        index_elements=["source_platform", "source_post_id"]
    )
    result = db.execute(stmt)
    return result.rowcount


# ---------------------------------------------------------------------------
# Main ingestion function
# ---------------------------------------------------------------------------

def run_ingestion() -> None:
    """
    Ingests tweets for all active Twitter sources.
    Intended to be called by the scheduler or directly from the CLI.
    """
    if not settings.twitter_bearer_token:
        log.error("TWITTER_BEARER_TOKEN is not set. Skipping ingestion.")
        return

    db: Session = SessionLocal()
    try:
        sources = (
            db.query(Source)
            .filter(Source.platform == "twitter", Source.active.is_(True))
            .all()
        )

        if not sources:
            log.info("No active Twitter sources found.")
            return

        log.info("Starting ingestion for %d source(s).", len(sources))

        with httpx.Client(
            headers={"Authorization": f"Bearer {settings.twitter_bearer_token}"},
            timeout=30.0,
        ) as client:
            for source in sources:
                log.info(
                    "Fetching source: type=%s value=%s",
                    source.source_type,
                    source.value,
                )
                try:
                    if source.source_type == "account":
                        rows = _fetch_user_timeline(client, source.value)
                    else:
                        # Both 'hashtag' and 'keyword' go through recent search.
                        # The source.value is used as-is (e.g. '#layananpublik'
                        # or 'keluhan infrastruktur') — both are valid query strings.
                        rows = _fetch_recent_search(client, source.value)

                    inserted = _insert_posts(db, rows)
                    log.info(
                        "Source %r: fetched %d tweet(s), inserted %d new.",
                        source.value,
                        len(rows),
                        inserted,
                    )

                    # Stamp the source regardless of whether rows were new.
                    source.last_scraped_at = datetime.now(tz=timezone.utc)
                    db.add(source)
                    db.commit()

                except httpx.HTTPStatusError as exc:
                    log.error(
                        "HTTP error fetching source %r: %s", source.value, exc
                    )
                    db.rollback()
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "Unexpected error for source %r: %s", source.value, exc
                    )
                    db.rollback()

        log.info("Ingestion complete.")
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
    )
    run_ingestion()
