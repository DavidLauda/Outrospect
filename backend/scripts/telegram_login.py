"""
One-time interactive login script for Telegram (MTProto / Telethon).

Run this script ONCE on a machine where you can receive SMS or Telegram
app notifications. It will print a session string that you then paste into
TELEGRAM_SESSION_STRING in your .env file.

After that, the ingestion service (app/services/ingest_telegram.py) uses
the session string directly — no interactive login, no phone needed at
runtime.

Usage (from backend/):
    python scripts/telegram_login.py

Requirements:
    TELEGRAM_API_ID and TELEGRAM_API_HASH must already be set in .env
    (or exported in the shell before running this script).

How to get API credentials:
    1. Go to https://my.telegram.org/auth
    2. Log in with your Telegram account's phone number.
    3. Navigate to "API development tools".
    4. Create an app (name/platform don't matter for personal use).
    5. Copy the api_id (integer) and api_hash (hex string) into .env.
"""

import asyncio
import os
import sys

# Load .env before importing app.config so the variables are available
# even when running this script standalone.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on the shell environment


async def main() -> None:
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        sys.exit(
            "telethon is not installed. Run: pip install telethon\n"
            "(or add it to requirements.txt and pip install -r requirements.txt)"
        )

    api_id_raw = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")

    if not api_id_raw or not api_hash:
        sys.exit(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env "
            "before running this script."
        )

    try:
        api_id = int(api_id_raw)
    except ValueError:
        sys.exit(f"TELEGRAM_API_ID must be an integer, got: {api_id_raw!r}")

    print(
        "\n=== Outrospect — Telegram session string generator ===\n"
        "You will be asked for your phone number and the login code\n"
        "that Telegram sends to your phone or another Telegram session.\n"
        "This is a one-time step.\n"
    )

    # StringSession("") starts a fresh in-memory session; Telethon will
    # prompt for credentials interactively via stdin.
    client = TelegramClient(StringSession(), api_id, api_hash)

    async with client:
        await client.start()  # triggers the interactive phone/code/2FA prompts

        session_string = client.session.save()

    print(
        "\n=== Login successful ===\n"
        "\nCopy the line below and add it to your .env file:\n"
    )
    print(f"TELEGRAM_SESSION_STRING={session_string}")
    print(
        "\nKeep this value secret — it grants full access to your Telegram account.\n"
        "Do NOT commit it to git. Confirm it is listed in .gitignore.\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
