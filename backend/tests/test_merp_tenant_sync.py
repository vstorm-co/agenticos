"""Minerp IAM tenant_ids ↔ Agentra organization mapping."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.iam_tenant import iam_may_access_minerp_tenant, parse_iam_tenant_ids

pytestmark = pytest.mark.anyio


class TestParseIamTenantIds:
    def test_parses_uuid_strings(self) -> None:
        t1, t2 = uuid4(), uuid4()
        payload = {"tenant_ids": [str(t1), str(t2), "not-a-uuid"]}
        assert parse_iam_tenant_ids(payload) == [t1, t2]

    def test_empty_when_missing(self) -> None:
        assert parse_iam_tenant_ids({}) == []


class TestIamMayAccessMinerpTenant:
    def test_global_scope_allows_any(self) -> None:
        tenant = uuid4()
        assert iam_may_access_minerp_tenant({"has_global_scope": True, "tenant_ids": []}, tenant)

    def test_requires_membership_in_tenant_ids(self) -> None:
        allowed, denied = uuid4(), uuid4()
        payload = {"tenant_ids": [str(allowed)], "has_global_scope": False}
        assert iam_may_access_minerp_tenant(payload, allowed) is True
        assert iam_may_access_minerp_tenant(payload, denied) is False
