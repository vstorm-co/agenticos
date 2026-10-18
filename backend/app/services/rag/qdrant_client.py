"""Shared Qdrant client factory (URL, API key, version check)."""

from __future__ import annotations

from qdrant_client import QdrantClient


def create_qdrant_client(*, url: str, api_key: str | None = None) -> QdrantClient:
    """Build a Qdrant client aligned with local/staging server image (v1.12.x)."""
    return QdrantClient(
        url=url,
        api_key=api_key or None,
        check_compatibility=True,
    )
