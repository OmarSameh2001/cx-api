"""Outbox handlers for files (registered through common.events.registry)."""

from loguru import logger

from common.events.registry import handler

from . import service


@handler("file.uploaded", "files.process_image")
def process_uploaded_image(db, event) -> None:
    """Server-side compression and thumbnail (the browser compresses first;
    this catches uploads that skipped it). Storage errors raise, so the relay
    retries with backoff; an unreadable image is marked failed, not retried."""
    outcome = service.process_image(db, int(event.payload["file_id"]))
    logger.info("file {}: {}", event.payload["file_id"], outcome)
