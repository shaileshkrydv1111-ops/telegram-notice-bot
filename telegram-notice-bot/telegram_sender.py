"""Telegram delivery layer.

Handles the three delivery modes required:
  1. PDF with 1-5 pages  -> render to images, send as one media group,
     caption on the first image only.
  2. PDF with > 5 pages  -> send the original PDF document with caption.
  3. No PDF              -> send a plain text message.

All outgoing text uses parse_mode=None (plain text) -- no Markdown/HTML,
no bold, no emojis, exactly the caption/message format required.
"""

from __future__ import annotations

import time

import requests

import config
from logger_setup import log

API_BASE = "https://api.telegram.org/bot{token}"


class TelegramError(RuntimeError):
    pass


def _url(method: str) -> str:
    return f"{API_BASE.format(token=config.TELEGRAM_BOT_TOKEN)}/{method}"


def _post_with_retry(method: str, *, data: dict | None = None, files: dict | None = None) -> dict:
    last_exc: Exception | None = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = requests.post(
                _url(method),
                data=data,
                files=files,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            payload = response.json()
            if not payload.get("ok"):
                raise TelegramError(f"Telegram API error on {method}: {payload}")
            return payload
        except (requests.RequestException, TelegramError, ValueError) as exc:
            last_exc = exc
            delay = config.RETRY_BACKOFF_SECONDS * attempt
            log.warning(
                "Telegram %s attempt %d/%d failed (%s). Retrying in %ds...",
                method,
                attempt,
                config.MAX_RETRIES,
                exc,
                delay,
            )
            if attempt < config.MAX_RETRIES:
                time.sleep(delay)
    raise TelegramError(f"Telegram {method} failed after {config.MAX_RETRIES} attempts: {last_exc}")


def send_text_message(text: str) -> None:
    _post_with_retry(
        "sendMessage",
        data={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
    )


def send_document(pdf_bytes: bytes, filename: str, caption: str) -> None:
    _post_with_retry(
        "sendDocument",
        data={"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption},
        files={"document": (filename, pdf_bytes, "application/pdf")},
    )


def send_photo_media_group(images: list[bytes], caption: str) -> None:
    """Send a list of PNG images as one media group. Caption is attached
    only to the first item, per Telegram's API semantics for media groups.
    """
    if not images:
        raise ValueError("No images to send")

    images = images[: config.TELEGRAM_MAX_MEDIA_GROUP_SIZE]

    media = []
    files = {}
    for index, image_bytes in enumerate(images):
        attach_name = f"page{index}"
        entry: dict = {"type": "photo", "media": f"attach://{attach_name}"}
        if index == 0:
            entry["caption"] = caption
        media.append(entry)
        files[attach_name] = (f"{attach_name}.png", image_bytes, "image/png")

    import json

    _post_with_retry(
        "sendMediaGroup",
        data={"chat_id": config.TELEGRAM_CHAT_ID, "media": json.dumps(media)},
        files=files,
    )


def verify_bot_credentials() -> bool:
    """Called during startup self-test to confirm the bot token/chat id work."""
    try:
        payload = _post_with_retry("getMe")
        bot_name = payload.get("result", {}).get("username", "unknown")
        log.info("Telegram bot credentials verified (bot: @%s).", bot_name)
        return True
    except TelegramError as exc:
        log.error("Telegram bot credential check failed: %s", exc)
        return False
