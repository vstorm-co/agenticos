"""IAM → AgenticOS permission overlay (B31.1)."""

from __future__ import annotations

import pytest

from app.core.iam_permission_bridge import (
    IAM_CONSOLE_READ,
    IAM_MCP_MANAGE,
    IAM_SYSTEM_ADMIN,
    iam_implies_app_admin,
    overlay_from_iam_codes,
)
from app.core.permissions import Perm, Scope

pytestmark = pytest.mark.security


def test_console_read_grants_member_baseline() -> None:
    overlay = overlay_from_iam_codes([IAM_CONSOLE_READ])
    assert overlay.get(Perm.AGENTS_VIEW) is Scope.SHARED
    assert overlay.get(Perm.AGENTS_EDIT) is Scope.OWN


def test_system_admin_grants_everything() -> None:
    overlay = overlay_from_iam_codes([IAM_SYSTEM_ADMIN])
    assert overlay[Perm.ORG_DELETE] is Scope.ALL


def test_mcp_manage_adds_manage_perms() -> None:
    overlay = overlay_from_iam_codes([IAM_CONSOLE_READ, IAM_MCP_MANAGE])
    assert overlay.get(Perm.MCP_MANAGE) is Scope.ALL


def test_global_scope_implies_app_admin() -> None:
    assert iam_implies_app_admin(codes=[], has_global_scope=True) is True
    assert iam_implies_app_admin(codes=[IAM_CONSOLE_READ], has_global_scope=False) is False
