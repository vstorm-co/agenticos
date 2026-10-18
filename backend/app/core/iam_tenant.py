"""Minerp IAM tenant_ids on JWT — parse and access checks."""

from __future__ import annotations

from typing import Any
from uuid import UUID


def parse_iam_tenant_ids(payload: dict[str, Any]) -> list[UUID]:
    raw = payload.get("tenant_ids")
    if not raw or not isinstance(raw, list):
        return []
    out: list[UUID] = []
    for item in raw:
        try:
            out.append(UUID(str(item)))
        except ValueError:
            continue
    return out


def iam_may_access_minerp_tenant(payload: dict[str, Any], tenant_id: UUID) -> bool:
    if payload.get("has_global_scope") is True:
        return True
    return tenant_id in parse_iam_tenant_ids(payload)
