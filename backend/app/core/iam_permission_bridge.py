"""Map minerp IAM JWT permission codes to AgenticOS :class:`Perm` scopes (B31.1)."""

from __future__ import annotations

from app.core.permissions import ROLE_PERMS, OrgRoleName, Perm, Scope

IAM_CONSOLE_READ = "agentra.console:read"
IAM_SESSION_READ = "agentra:session:read"
IAM_MCP_READ = "agentra.mcp:read"
IAM_MCP_MANAGE = "agentra.mcp:manage"
IAM_AGENT_PUBLISH = "agentra.agent:publish"
IAM_SYSTEM_ADMIN = "system:admin"


def _merge_into(target: dict[Perm, Scope], source: dict[Perm, Scope]) -> None:
    for perm, scope in source.items():
        current = target.get(perm, Scope.NONE)
        target[perm] = current if current >= scope else scope


def overlay_from_iam_codes(codes: list[str]) -> dict[Perm, Scope]:
    """Effective AgenticOS permission overlay from IAM JWT ``permissions`` claim."""
    normalized = {str(c).strip() for c in codes if c}
    if IAM_SYSTEM_ADMIN in normalized:
        return dict.fromkeys(Perm, Scope.ALL)

    overlay: dict[Perm, Scope] = {}

    if IAM_CONSOLE_READ in normalized or IAM_SESSION_READ in normalized:
        _merge_into(overlay, dict(ROLE_PERMS.get(OrgRoleName.MEMBER, {})))

    if IAM_MCP_READ in normalized:
        _merge_into(
            overlay,
            {
                Perm.AGENTS_VIEW: Scope.ALL,
                Perm.CONNECTIONS_VIEW: Scope.ALL,
                Perm.RUNS_VIEW: Scope.ALL,
            },
        )

    if IAM_MCP_MANAGE in normalized:
        _merge_into(
            overlay,
            {
                Perm.MCP_MANAGE: Scope.ALL,
                Perm.CONNECTIONS_MANAGE: Scope.ALL,
                Perm.SECRETS_VIEW: Scope.ALL,
                Perm.SECRETS_EDIT: Scope.ALL,
                Perm.CHANNELS_MANAGE: Scope.ALL,
            },
        )

    if IAM_AGENT_PUBLISH in normalized:
        _merge_into(
            overlay,
            {
                Perm.AGENTS_VIEW: Scope.ALL,
                Perm.AGENTS_EDIT: Scope.ALL,
                Perm.AGENTS_PUBLISH: Scope.ALL,
            },
        )

    return overlay


def iam_implies_app_admin(*, codes: list[str], has_global_scope: bool) -> bool:
    if has_global_scope:
        return True
    return IAM_SYSTEM_ADMIN in {str(c).strip() for c in codes if c}
