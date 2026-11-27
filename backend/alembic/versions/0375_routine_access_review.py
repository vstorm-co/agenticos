"""One access review per routine: its sources and a setting for each tool.

A routine's sources and its approvals were overlapping models: the source
review's `follow_agent` / `restricted` mode, `action_mode`, the version-bound
`action_consents` and the per-tool `tool_settings` narrowing
(`0365_routine_tool_settings.py`). They become one review in
`agent_triggers.approved_sources` (`RoutineSourcePolicy`): mode `reviewed` or
`trust_agent`, a ceiling of sources, and `allow` / `ask` / `off` per tool
(`docs/design/routine-access.md`).

Every routine converts in place, so none gains authority and none stops:

- `action_mode = agent`, or no mode under `follow_agent`, ran every tool as the
  agent allows without a permission check. It becomes `grandfathered`, which
  keeps exactly that until the creator next saves the review.
- `per_tool` keeps as `allow` the consents bound to the reviewed version, the
  ones that still applied; an effectful tool without one asks, as before.
- `manual` keeps no `allow`.
- Delegates' effectful tools were free only under the agent's settings.

Reviews converted here carry no `intent_hash`, so a later prompt edit is not
detected until they are saved again. Parked runs' snapshots convert the same
way so they can resume. `organizations.routines_may_trust_agent` is new and off.

`downgrade()` restores the columns, `tool_settings` empty. Grandfathered and trusting reviews return
to `action_mode = agent`, every other one to `per_tool` without consents, so
those routines ask again; parked runs' snapshots are left as they are.
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0375_routine_access_review"
down_revision: str | None = "0374_case_from_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNFINISHED = ("running", "awaiting_approval", "awaiting_answer")


def _key(entry: dict[str, Any]) -> dict[str, Any] | None:
    """A consent's or setting's tool, as the review keys it, or None if unreadable."""
    tool = entry.get("tool_id")
    if not isinstance(tool, str):
        return None
    if entry.get("kind") == "platform":
        return {"kind": "platform", "tool_id": tool}
    if isinstance(entry.get("capability_id"), str):
        return {"capability_id": entry["capability_id"], "tool_id": tool}
    if isinstance(entry.get("connection_id"), str):
        return {"connection_id": entry["connection_id"], "tool_id": tool}
    return None


def _reviewed(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    converted = {key: item for key, item in value.items() if key != "mode"}
    converted["mode"] = "reviewed"
    return converted


def _review(
    policy: dict[str, Any] | None,
    action_mode: str | None,
    consents: list[dict[str, Any]],
    settings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(policy, dict):
        return policy
    if policy.get("pending_review") is True:
        return {key: item for key, item in policy.items() if key != "mode"}
    mode = action_mode or ("agent" if policy.get("mode") == "follow_agent" else "per_tool")
    review = _reviewed(policy)
    assert review is not None
    if isinstance(policy.get("approved_ceiling"), dict):
        review["approved_ceiling"] = _reviewed(policy["approved_ceiling"])
    tools: dict[str, dict[str, Any]] = {}
    for setting in settings:
        key = _key(setting)
        if key is not None and setting.get("setting") in ("ask", "off"):
            tools[json.dumps(key, sort_keys=True)] = {**key, "setting": setting["setting"]}
    if mode == "agent":
        review["grandfathered"] = True
        review["delegates"] = "allow"
    else:
        review["delegates"] = "ask"
    if mode == "per_tool":
        for consent in consents:
            key = _key(consent)
            if key is None or consent.get("version_id") != policy.get("version_id"):
                continue
            tools.setdefault(json.dumps(key, sort_keys=True), {**key, "setting": "allow"})
    review["tools"] = [tools[name] for name in sorted(tools)]
    return review


def _legacy(policy: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    """A review as the previous schema reads it, and the action mode it ran under."""
    if not isinstance(policy, dict):
        return policy, "per_tool"
    if policy.get("pending_review") is True:
        return {**policy, "mode": "restricted"}, "agent"
    action_mode = (
        "agent"
        if policy.get("grandfathered") or policy.get("mode") == "trust_agent"
        else "per_tool"
    )

    def sources(value: dict[str, Any]) -> dict[str, Any]:
        kept = {
            key: item
            for key, item in value.items()
            if key not in ("tools", "delegates", "intent_hash", "grandfathered", "platform")
        }
        kept["mcp_sources"] = {
            key: {
                name: field
                for name, field in account.items()
                if name not in ("account", "personal")
            }
            for key, account in (value.get("mcp_sources") or {}).items()
        }
        if isinstance(value.get("input_source"), dict):
            kept["input_source"] = {
                name: field
                for name, field in value["input_source"].items()
                if name not in ("account", "personal")
            }
        return kept

    ceiling = policy.get("approved_ceiling")
    legacy = sources(policy)
    if isinstance(ceiling, dict) and ceiling.get("behavior") is not None:
        legacy["mode"] = "follow_agent"
        legacy["approved_ceiling"] = {**sources(ceiling), "mode": "follow_agent"}
    else:
        legacy["mode"] = "restricted"
        legacy["behavior"] = None
        legacy.pop("approved_ceiling", None)
    return legacy, action_mode


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, approved_sources, action_mode, action_consents, tool_settings "
            "FROM agent_triggers WHERE approved_sources IS NOT NULL"
        )
    ).all()
    for row in rows:
        review = _review(
            row.approved_sources,
            row.action_mode,
            row.action_consents or [],
            row.tool_settings or [],
        )
        bind.execute(
            sa.text(
                "UPDATE agent_triggers SET approved_sources = :review WHERE id = :id"
            ).bindparams(sa.bindparam("review", type_=postgresql.JSONB)),
            {"review": review, "id": row.id},
        )
    runs = bind.execute(
        sa.text(
            "SELECT id, routine_policy FROM agent_runs WHERE routine_kind = 'trigger' "
            "AND routine_policy ? 'approved_sources' AND status IN :unfinished"
        ).bindparams(sa.bindparam("unfinished", expanding=True)),
        {"unfinished": list(_UNFINISHED)},
    ).all()
    for run in runs:
        snapshot = dict(run.routine_policy)
        snapshot["approved_sources"] = _review(
            snapshot.get("approved_sources"),
            snapshot.pop("action_mode", None),
            snapshot.pop("action_consents", None) or [],
            snapshot.pop("tool_settings", None) or [],
        )
        bind.execute(
            sa.text("UPDATE agent_runs SET routine_policy = :snapshot WHERE id = :id").bindparams(
                sa.bindparam("snapshot", type_=postgresql.JSONB)
            ),
            {"snapshot": snapshot, "id": run.id},
        )
    # `delivery_conversation_id` is a deferred foreign key: an upgrade that ran an
    # earlier revision rewriting these rows in the same transaction leaves its
    # checks pending, and Postgres refuses to alter a table that has any.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.drop_constraint("ck_trigger_action_mode", "agent_triggers", type_="check")
    op.drop_column("agent_triggers", "action_mode")
    op.drop_column("agent_triggers", "action_consents")
    op.drop_column("agent_triggers", "tool_settings")
    op.add_column(
        "organizations",
        sa.Column("routines_may_trust_agent", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("organizations", "routines_may_trust_agent")
    op.add_column(
        "agent_triggers",
        sa.Column(
            "tool_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column(
        "agent_triggers",
        sa.Column("action_mode", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "agent_triggers",
        sa.Column(
            "action_consents",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_trigger_action_mode",
        "agent_triggers",
        "action_mode IS NULL OR action_mode IN ('agent', 'manual', 'per_tool')",
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, approved_sources FROM agent_triggers WHERE approved_sources IS NOT NULL"
        )
    ).all()
    for row in rows:
        legacy, action_mode = _legacy(row.approved_sources)
        bind.execute(
            sa.text(
                "UPDATE agent_triggers SET approved_sources = :legacy, action_mode = :mode "
                "WHERE id = :id"
            ).bindparams(sa.bindparam("legacy", type_=postgresql.JSONB)),
            {"legacy": legacy, "mode": action_mode, "id": row.id},
        )
