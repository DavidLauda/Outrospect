"""
LLM classification service.

Picks up unclassified posts and sends each one's text to the LLM API,
then writes the result into `classifications`.

Usage (manual run from backend/):
    python -m app.services.classify [--batch-size N]

Called by the APScheduler job in app/jobs/classify.py once wired up.
"""

import argparse
import hashlib
import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.db import SessionLocal
from app.models.classification import Classification
from app.models.post import Post

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt definition
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are classifying social media posts that discuss Indonesian government
services, infrastructure, or officials. For each post, output ONLY a JSON
object with this exact shape — no preamble, no markdown fences:

{
  "category": "infrastructure" | "public_service" | "corruption" | "other",
  "sentiment": "negative" | "neutral" | "mixed",
  "referenced_agency": string or null,
  "region": string or null,
  "confidence": number between 0 and 1
}

Category definitions:
- infrastructure: roads, drainage, public utilities, transportation
- public_service: bureaucracy, document processing (KTP/KK/SIM), healthcare
  or education service delivery
- corruption: allegations of bribery, misuse of funds, nepotism
- other: doesn't clearly fit the above, or is not actually a complaint

If the post is not a complaint or criticism at all (e.g. it's praise, or
unrelated to government), still classify it — sentiment may be "neutral"
or omit "negative", and category can be "other".

Only extract "referenced_agency" or "region" if they are explicitly named
or very strongly implied — otherwise return null. Do not guess.\
"""

# Few-shot examples injected into the first user turn so the model sees
# concrete calibration for informal Bahasa Indonesia before the real post.
FEW_SHOT_BLOCK = """\
Here are some examples of the classification task:

Input: "Jalan di depan komplek udah bolong gede banget dari 3 bulan lalu, laporan ke kelurahan gak ditanggepin sama sekali"
Output: {"category": "infrastructure", "sentiment": "negative", "referenced_agency": "Kelurahan", "region": null, "confidence": 0.9}

Input: "udah 2 minggu urus KTP di Dukcapil belum jadi jadi, padahal katanya cuma 3 hari kerja"
Output: {"category": "public_service", "sentiment": "negative", "referenced_agency": "Dukcapil", "region": null, "confidence": 0.92}

Input: "dengar-dengar dana bansos di desa sebelah banyak yang gak sampe ke warga, katanya dipotong oknum perangkat desa"
Output: {"category": "corruption", "sentiment": "negative", "referenced_agency": "Perangkat Desa", "region": null, "confidence": 0.75}

Input: "pelayanan puskesmas deket rumah gue lumayan cepet kok tadi pagi"
Output: {"category": "public_service", "sentiment": "neutral", "referenced_agency": "Puskesmas", "region": null, "confidence": 0.7}

Now classify the following post. Output ONLY the JSON object:\
"""

# ---------------------------------------------------------------------------
# Model version string
# ---------------------------------------------------------------------------
# Changing the prompt text automatically changes PROMPT_HASH, so every
# classification row carries a traceable version of the prompt that produced it.

_PROMPT_HASH = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:8]


def _model_version(model_name: str) -> str:
    return f"{model_name}@prompt-{_PROMPT_HASH}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_CATEGORIES = {"infrastructure", "public_service", "corruption", "other"}
_VALID_SENTIMENTS = {"negative", "neutral", "mixed"}


def _validate(data: dict[str, Any]) -> None:
    """Raises ValueError if the LLM output is missing required keys or has invalid values."""
    for key in ("category", "sentiment", "confidence"):
        if key not in data:
            raise ValueError(f"Missing required key: {key!r}")
    if data["category"] not in _VALID_CATEGORIES:
        raise ValueError(f"Unknown category: {data['category']!r}")
    if data["sentiment"] not in _VALID_SENTIMENTS:
        raise ValueError(f"Unknown sentiment: {data['sentiment']!r}")
    conf = data["confidence"]
    if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
        raise ValueError(f"confidence must be 0–1, got: {conf!r}")


# ---------------------------------------------------------------------------
# LLM API call (OpenAI-compatible)
# ---------------------------------------------------------------------------

def _call_llm(client: httpx.Client, text: str) -> dict[str, Any]:
    """
    Sends a single post's text to the LLM and returns the parsed JSON dict.
    Raises ValueError if the response cannot be parsed or fails validation.
    Raises httpx.HTTPStatusError on non-2xx API responses.
    """
    user_content = f"{FEW_SHOT_BLOCK}\n\nPost: {text}"

    response = client.post(
        "https://api.openai.com/v1/chat/completions",
        json={
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,   # deterministic; classification is not creative
            "max_tokens": 200,
        },
    )
    response.raise_for_status()

    raw_content = response.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown fences in case the model adds them despite the instruction.
    if raw_content.startswith("```"):
        raw_content = raw_content.split("```")[1]
        if raw_content.startswith("json"):
            raw_content = raw_content[4:]

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON: {raw_content!r}") from exc

    _validate(data)
    return data


# ---------------------------------------------------------------------------
# Main classification function
# ---------------------------------------------------------------------------

def run_classification(batch_size: int = 20) -> None:
    """
    Classifies up to `batch_size` unclassified posts.
    Posts without a matching classification row are picked up in posted_at order.
    """
    if not settings.llm_api_key:
        log.error("LLM_API_KEY is not set. Skipping classification.")
        return

    db = SessionLocal()
    try:
        # LEFT JOIN to find posts with no classification row yet.
        unclassified = (
            db.query(Post)
            .outerjoin(Classification, Post.id == Classification.post_id)
            .filter(Classification.id.is_(None))
            .order_by(Post.posted_at.asc())
            .limit(batch_size)
            .all()
        )

        if not unclassified:
            log.info("No unclassified posts found.")
            return

        log.info("Classifying %d post(s).", len(unclassified))
        model_ver = _model_version(settings.llm_model)
        succeeded = 0
        skipped = 0

        with httpx.Client(
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        ) as client:
            for post in unclassified:
                try:
                    result = _call_llm(client, post.content_text)
                except ValueError as exc:
                    log.warning(
                        "Skipping post %d — parse/validation error: %s", post.id, exc
                    )
                    skipped += 1
                    continue
                except httpx.HTTPStatusError as exc:
                    log.error(
                        "Skipping post %d — API error: %s", post.id, exc
                    )
                    skipped += 1
                    continue

                classification = Classification(
                    post_id=post.id,
                    category=result["category"],
                    sentiment=result["sentiment"],
                    referenced_agency=result.get("referenced_agency"),
                    region=result.get("region"),
                    confidence=result.get("confidence"),
                    model_version=model_ver,
                )
                db.add(classification)
                db.commit()
                succeeded += 1
                log.info(
                    "Post %d classified: category=%s sentiment=%s confidence=%.2f",
                    post.id,
                    result["category"],
                    result["sentiment"],
                    result.get("confidence", 0),
                )

        log.info(
            "Batch complete. Classified: %d, skipped: %d.", succeeded, skipped
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(
        description="Classify unclassified posts using the LLM API."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        metavar="N",
        help="Number of posts to process per run (default: 20).",
    )
    args = parser.parse_args()
    run_classification(batch_size=args.batch_size)
