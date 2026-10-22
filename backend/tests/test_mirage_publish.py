"""Publishing an agent with a virtual terminal, and the runner handing it its folders (#2191).

Publish is where the parts only the database can answer are refused: a secret the
publisher may not lend, an account the organization does not have, a typed host
the operator has not allowed. The runner resolves what is left for each run.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.mirage import MIRAGE_MOUNTS_RESOURCE, MirageConfig, ResolvedTerminal
from app.agents.spec import AgentSpec
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import SecretKind
from app.services import agent_runner
from app.services.agent_registry import AgentRegistryService

pytestmark = pytest.mark.anyio

TOKEN = uuid.uuid4()
APP = uuid.uuid4()
ACCOUNT = uuid.uuid4()


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _config() -> MirageConfig:
    return MirageConfig.model_validate(
        {
            "mounts": [
                {
                    "path": "/code/",
                    "backend": "github",
                    "secrets": {"token": str(TOKEN)},
                    "options": {"owner": "o", "repo": "r"},
                },
                {"path": "/files/", "backend": "onedrive", "secrets": {"app": str(APP)}},
                {
                    "path": "/drive/",
                    "backend": "gdrive",
                    "account": {"kind": "organization", "connection_id": str(ACCOUNT)},
                },
                {"path": "/mail/", "backend": "gmail", "account": {"kind": "personal"}},
                {"path": "/box/", "backend": "ssh", "options": {"host": "build.acme.internal"}},
                {"path": "/scratch/", "backend": "ram"},
            ]
        }
    )


async def _problems(ctx, config, *, secrets=None, access=True, account=None, hosts=()):
    stored = secrets or {}
    with (
        patch(
            "app.services.agent_registry.organization_secret_repo.get",
            new=AsyncMock(side_effect=lambda db, secret_id, organization_id: stored.get(secret_id)),
        ),
        patch("app.services.agent_registry.resolve_access", new=AsyncMock(return_value=access)),
        patch(
            "app.services.agent_registry.mcp_connection_repo.get_account",
            new=AsyncMock(return_value=account),
        ),
        patch.object(settings, "MIRAGE_ALLOWED_HOSTS", list(hosts)),
    ):
        return await AgentRegistryService(MagicMock())._mirage_problems(ctx, config)


async def test_a_terminal_whose_every_reference_holds_publishes() -> None:
    ctx = _ctx()
    problems = await _problems(
        ctx,
        _config(),
        secrets={
            TOKEN: SimpleNamespace(kind=SecretKind.API_KEY.value, name="gh"),
            APP: SimpleNamespace(kind=SecretKind.ENTRA_APP.value, name="entra"),
        },
        account=SimpleNamespace(organization_id=ctx.organization_id),
        hosts=["build.acme.internal"],
    )
    assert problems == []


async def test_what_the_publisher_cannot_lend_is_named_folder_by_folder() -> None:
    ctx = _ctx()
    problems = await _problems(
        ctx,
        _config(),
        secrets={TOKEN: SimpleNamespace(kind=SecretKind.ENTRA_APP.value, name="wrong")},
        account=SimpleNamespace(organization_id=uuid.uuid4()),
    )
    assert problems == [
        "/code/ needs a api_key secret for token, but 'wrong' holds a entra_app",
        f"/files/ points at a secret this organization does not have: {APP}",
        "/drive/ reads an account the organization has not connected",
        "/box/: host names a host this deployment does not allow; an operator adds it to MIRAGE_ALLOWED_HOSTS",
    ]


async def test_a_secret_the_publisher_may_not_see_is_reported_as_missing() -> None:
    problems = await _problems(
        _ctx(),
        MirageConfig.model_validate(
            {
                "mounts": [
                    {
                        "path": "/code/",
                        "backend": "github",
                        "secrets": {"token": str(TOKEN)},
                        "options": {"owner": "o", "repo": "r"},
                    }
                ]
            }
        ),
        secrets={TOKEN: SimpleNamespace(kind=SecretKind.API_KEY.value, name="gh")},
        access=False,
    )
    assert problems == [f"/code/ points at a secret this organization does not have: {TOKEN}"]


async def test_a_backend_gone_since_the_config_validated_is_skipped_here() -> None:
    with patch("app.services.agent_registry.mirage_backend", return_value=None):
        assert await _problems(_ctx(), _config()) == []


async def test_publish_runs_the_terminal_checks_for_a_terminal_binding() -> None:
    service = AgentRegistryService(MagicMock())
    service._mirage_problems = AsyncMock(return_value=["/x/ is wrong"])
    service._secret_problems = AsyncMock(return_value=[])
    binding = SimpleNamespace(
        id="mirage",
        config={"mounts": [{"path": "/scratch/", "backend": "ram"}]},
        secret_id=None,
        tool_approval={},
        tool_overrides={},
        enabled=True,
    )
    problems = await service._binding_problems(_ctx(), binding)  # ty: ignore[invalid-argument-type]
    assert "/x/ is wrong" in str(problems)


# -- the runner ----------------------------------------------------------------


def _spec(*capabilities: dict) -> AgentSpec:
    return AgentSpec.model_validate({"name": "a", "capabilities": list(capabilities)})


def test_the_runner_reads_a_terminal_only_from_an_enabled_binding() -> None:
    enabled = _spec(
        {"id": "mirage", "config": {"mounts": [{"path": "/scratch/", "backend": "ram"}]}}
    )
    disabled = _spec(
        {
            "id": "mirage",
            "enabled": False,
            "config": {"mounts": [{"path": "/scratch/", "backend": "ram"}]},
        }
    )
    assert isinstance(agent_runner._mirage_config(enabled), MirageConfig)
    assert agent_runner._mirage_config(disabled) is None
    assert agent_runner._mirage_config(_spec({"id": "clock"})) is None


async def test_the_runner_leaves_the_resolved_folders_for_the_capability(monkeypatch) -> None:
    resolved = ResolvedTerminal(mounts=())
    service = MagicMock()
    service.return_value.resolve = AsyncMock(return_value=resolved)
    monkeypatch.setattr(agent_runner, "MirageMountService", service)
    runner = agent_runner.AgentRunnerService.__new__(agent_runner.AgentRunnerService)
    runner.db = MagicMock()
    ctx, person = _ctx(), uuid.uuid4()

    resources: dict = {}
    await runner._add_mirage_terminal(
        resources,
        ctx,
        _spec({"id": "mirage", "config": {"mounts": [{"path": "/scratch/", "backend": "ram"}]}}),
        person_id=person,
    )
    assert resources[MIRAGE_MOUNTS_RESOURCE] is resolved
    assert service.return_value.resolve.await_args.kwargs == {"person_id": person}

    untouched: dict = {}
    await runner._add_mirage_terminal(untouched, ctx, _spec({"id": "clock"}), person_id=None)
    assert untouched == {}
