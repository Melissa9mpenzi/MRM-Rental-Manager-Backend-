"""Walrus decentralized storage — store lease docs and receipt JSON hashes."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import httpx

from app.config import settings


def is_walrus_configured() -> bool:
    return bool((settings.walrus_publisher_url or "").strip())


def store_json(payload: dict[str, Any], *, epochs: int = 5) -> Optional[str]:
    """
    Publish JSON blob to Walrus. Returns blob id / quilt id when configured.
    When Walrus is not configured, returns a deterministic content hash for demo anchoring.
    """
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    content_hash = hashlib.sha256(raw).hexdigest()

    publisher = (settings.walrus_publisher_url or "").strip().rstrip("/")
    if not publisher:
        return f"hash:{content_hash}"

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
    return str(data.get("blobId") or data.get("id") or f"hash:{content_hash}")


def public_url(blob_id: str) -> Optional[str]:
    if not blob_id or blob_id.startswith("hash:"):
        return None
    base = (settings.walrus_aggregator_url or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/v1/blobs/{blob_id}"
