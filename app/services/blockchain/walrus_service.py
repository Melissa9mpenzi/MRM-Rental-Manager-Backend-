"""Walrus decentralized storage — publish JSON blobs when publisher is configured."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class WalrusStoreResult:
    """Result of anchoring JSON — never masquerade hash-only as a live Walrus blob."""

    content_hash: str
    walrus_blob_id: Optional[str] = None
    walrus_live: bool = False

    @property
    def storage_label(self) -> str:
        if self.walrus_live and self.walrus_blob_id:
            return "walrus"
        return "content_hash"


def is_walrus_configured() -> bool:
    return bool((settings.walrus_publisher_url or "").strip())


def store_json(payload: dict[str, Any], *, epochs: int = 5) -> WalrusStoreResult:
    """
    Publish JSON to Walrus when ``WALRUS_PUBLISHER_URL`` is set.
    Always returns SHA-256 content hash; ``walrus_blob_id`` is set only after a successful publish.
    """
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    content_hash = hashlib.sha256(raw).hexdigest()

    publisher = (settings.walrus_publisher_url or "").strip().rstrip("/")
    if not publisher:
        if settings.is_production:
            logger.warning(
                "WALRUS_PUBLISHER_URL not set in production — storing content hash only for %s",
                payload.get("artifact_type", "artifact"),
            )
        return WalrusStoreResult(content_hash=content_hash, walrus_blob_id=None, walrus_live=False)

    try:
        with httpx.Client(timeout=60.0) as client:
            res = client.put(
                f"{publisher}/v1/blobs",
                params={"epochs": epochs},
                content=raw,
                headers={"Content-Type": "application/json"},
            )
        if res.status_code not in (200, 201):
            raise ValueError(f"Walrus publish failed ({res.status_code}): {res.text[:200]}")
        data = res.json() if res.content else {}
        blob_id = str(data.get("blobId") or data.get("id") or "").strip()
        if not blob_id or blob_id.startswith("hash:"):
            raise ValueError("Walrus returned empty blob id")
        return WalrusStoreResult(content_hash=content_hash, walrus_blob_id=blob_id, walrus_live=True)
    except Exception as exc:
        logger.error("Walrus publish failed: %s", exc)
        if settings.is_production:
            raise
        return WalrusStoreResult(content_hash=content_hash, walrus_blob_id=None, walrus_live=False)


def public_url(blob_id: Optional[str]) -> Optional[str]:
    if not blob_id or str(blob_id).startswith("hash:"):
        return None
    base = (settings.walrus_aggregator_url or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/v1/blobs/{blob_id}"
