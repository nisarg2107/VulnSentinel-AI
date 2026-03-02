"""Helper utilities for worker orchestration."""

from __future__ import annotations

import logging

import pika

from grype_logic import detect_grype_version
from syft_logic import detect_syft_version


# Extract image name without digest suffix.
def image_name_from_ref(image_ref: str) -> str:
    if "@sha256:" in image_ref:
        return image_ref.split("@", 1)[0]
    return image_ref


# Build a digest-pinned image reference from asset fields.
def image_ref_from_asset(image_name: str, image_digest: str) -> str:
    base = image_name.split("@", 1)[0]
    return f"{base}@{image_digest}"


# Detect tool versions once and keep errors visible in metadata.
def detect_tool_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    try:
        versions["syft"] = detect_syft_version()
    except Exception as exc:  # pragma: no cover
        versions["syft"] = f"error: {exc}"

    try:
        versions["grype"] = detect_grype_version()
    except Exception as exc:  # pragma: no cover
        versions["grype"] = f"error: {exc}"

    return versions


# ACK safely so shutdown races do not crash the consumer.
def safe_ack(ch: pika.adapters.blocking_connection.BlockingChannel, delivery_tag: int) -> None:
    try:
        if not ch.is_open:
            logging.warning("Skipping ACK delivery_tag=%s because channel is not open", delivery_tag)
            return
        connection = getattr(ch, "connection", None)
        if connection is not None and not connection.is_open:
            logging.warning("Skipping ACK delivery_tag=%s because connection is not open", delivery_tag)
            return
        ch.basic_ack(delivery_tag=delivery_tag)
    except Exception as exc:  # pragma: no cover
        logging.warning("ACK failed for delivery_tag=%s: %s", delivery_tag, exc)


# NACK safely so shutdown races do not crash the consumer.
def safe_nack(ch: pika.adapters.blocking_connection.BlockingChannel, delivery_tag: int, requeue: bool) -> None:
    try:
        if not ch.is_open:
            logging.warning("Skipping NACK delivery_tag=%s because channel is not open", delivery_tag)
            return
        connection = getattr(ch, "connection", None)
        if connection is not None and not connection.is_open:
            logging.warning("Skipping NACK delivery_tag=%s because connection is not open", delivery_tag)
            return
        ch.basic_nack(delivery_tag=delivery_tag, requeue=requeue)
    except Exception as exc:  # pragma: no cover
        logging.warning("NACK failed for delivery_tag=%s: %s", delivery_tag, exc)
