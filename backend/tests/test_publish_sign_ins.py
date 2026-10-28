"""Publishing on a ChatGPT sign-in the publisher cannot use is refused (#2546).

A sign-in is one person's subscription. A run reaches it only for somebody who
may see it in the vault, and publishing an agent on it decides whose runs those
are - so the publisher is held to the same `secrets:view` the runtime asks of a
caller. These tests mock the repositories and `resolve_access`; the role scopes
and grants deciding it against real rows are in
`tests/integration/test_publish_sign_in_access.py`.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities import load_builtins
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import SecretKind
from app.services.agent_registry import AgentRegistryService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

REGISTRY_PATH = "app.services.agent_registry"
ORG = uuid.uuid4()


@pytest.fixture(autouse=True)
def _builtins_loaded() -> None:
    load_builtins()


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role=OrgRoleName.BUILDER)


def _secret(kind: SecretKind) -> MagicMock:
    secret = MagicMock(id=uuid.uuid4(), organization_id=ORG, kind=kind.value)
    secret.name = "Ada's ChatGPT"
    return secret


def _profile(label: str, *, secret: MagicMock | None, fallbacks: tuple = ()) -> MagicMock:
    profile = MagicMock(
        id=uuid.uuid4(),
        secret_id=secret.id if secret is not None else None,
        fallback_profile_ids=[str(fallback.id) for fallback in fallbacks],
    )
    profile.label = label
    return profile


class _Vault:
    """The organization's profiles and secrets, and which secrets the caller may see."""

    def __init__(self, *profiles: MagicMock, secrets: tuple = (), visible: tuple = ()) -> None:
        self.profiles = {profile.id: profile for profile in profiles}
        self.secrets = {secret.id: secret for secret in secrets}
        self.visible = {secret.id for secret in visible}
        self.access = AsyncMock(side_effect=self._may_see)

    async def _profiles(self, _db, ids, **_kwargs):
        return {pid: self.profiles[pid] for pid in ids if pid in self.profiles}

    async def _secrets(self, _db, ids, **_kwargs):
        return {sid: self.secrets[sid] for sid in ids if sid in self.secrets}

    async def _may_see(self, _db, _ctx, secret, *_args, **_kwargs) -> bool:
        return secret.id in self.visible

    @contextmanager
    def patched(self) -> Iterator[None]:
        with (
            patch(f"{REGISTRY_PATH}.credential_repo.get_profiles_by_ids", new=self._profiles),
            patch(f"{REGISTRY_PATH}.organization_secret_repo.get_many", new=self._secrets),
            patch(f"{REGISTRY_PATH}.resolve_access", new=self.access),
        ):
            yield

    async def problems(self, spec: AgentSpec):
        with self.patched():
            return await AgentRegistryService(MagicMock())._sign_in_problems(_ctx(), spec)


def _spec(**fields) -> AgentSpec:
    return AgentSpec.model_validate({"name": "Helpdesk", **fields})


class TestTheAgentsOwnModel:
    async def test_a_sign_in_the_publisher_cannot_see_is_refused_on_the_field(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        model = _profile("Ada's Codex", secret=sign_in)
        vault = _Vault(model, secrets=(sign_in,))

        problems = await vault.problems(_spec(model_profile_id=str(model.id)))

        message = (
            "Model 'Ada's Codex' runs on somebody's own ChatGPT sign-in, which you cannot "
            "use - pick another model, or ask its owner to share the sign-in with you"
        )
        assert problems.messages == [message]
        assert problems.fields == [{"field": "model_profile_id", "message": message}]
        assert "Ada's ChatGPT" not in message, "the publisher cannot see the secret's name"

    async def test_a_sign_in_the_publisher_can_see_is_allowed(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        model = _profile("My Codex", secret=sign_in)
        vault = _Vault(model, secrets=(sign_in,), visible=(sign_in,))

        problems = await vault.problems(_spec(model_profile_id=str(model.id)))

        assert problems.messages == []

    async def test_an_api_key_is_not_asked_about_at_all(self):
        """Only a sign-in is somebody's own; any other key is the organization's
        to spend, and its visibility is the key's binding checks, not this one."""
        key = _secret(SecretKind.API_KEY)
        model = _profile("GPT", secret=key)
        keyless = _profile("Ollama", secret=None)
        vault = _Vault(model, keyless, secrets=(key,))

        problems = await vault.problems(
            _spec(
                model_profile_id=str(model.id),
                reviewers=[{"name": "tone", "model_profile_id": str(keyless.id)}],
                # Follow-ups on no model of its own runs on the agent's.
                capabilities=[{"id": "follow_ups"}],
            )
        )

        assert problems.messages == []
        vault.access.assert_not_awaited()

    async def test_a_profile_that_is_gone_is_left_to_the_profile_check(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        other = _profile("Ada's Codex", secret=sign_in)
        vault = _Vault(other, secrets=(sign_in,))

        problems = await vault.problems(
            _spec(
                model_profile_id=str(uuid.uuid4()),
                reviewers=[{"name": "tone", "model_profile_id": str(other.id)}],
            )
        )

        assert problems.fields == [
            {"field": "reviewers.0.model_profile_id", "message": problems.messages[0]}
        ]

    async def test_a_spec_naming_no_model_asks_nothing(self):
        vault = _Vault()
        with patch(f"{REGISTRY_PATH}.credential_repo.get_profiles_by_ids") as lookup:
            problems = await vault.problems(_spec())
        assert problems.messages == []
        lookup.assert_not_called()


class TestFallbacks:
    async def test_a_fallback_on_a_sign_in_the_publisher_cannot_see_is_refused(self):
        """An outage hands the run to the fallback, so a chain is a choice of what
        a run spends as much as the model itself is."""
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        key = _secret(SecretKind.API_KEY)
        codex = _profile("Ada's Codex", secret=sign_in)
        model = _profile("GPT", secret=key, fallbacks=(codex,))
        vault = _Vault(model, codex, secrets=(sign_in, key))

        problems = await vault.problems(_spec(model_profile_id=str(model.id)))

        assert problems.fields == [
            {
                "field": "model_profile_id",
                "message": (
                    "Model 'GPT' falls back to 'Ada's Codex', which runs on somebody's own "
                    "ChatGPT sign-in you cannot use - remove it from the fallbacks, or ask "
                    "its owner to share the sign-in with you"
                ),
            }
        ]

    async def test_only_the_fallbacks_a_run_can_reach_are_judged(self):
        key = _secret(SecretKind.API_KEY)
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        reachable = [_profile(f"Spare {n}", secret=key) for n in range(3)]
        past_the_end = _profile("Ada's Codex", secret=sign_in)
        model = _profile("GPT", secret=key, fallbacks=(*reachable, past_the_end))
        vault = _Vault(model, *reachable, past_the_end, secrets=(key, sign_in))

        problems = await vault.problems(_spec(model_profile_id=str(model.id)))

        assert problems.messages == []

    async def test_a_fallback_that_is_gone_is_skipped(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        codex = _profile("Ada's Codex", secret=sign_in)
        model = _profile("GPT", secret=None, fallbacks=(MagicMock(id=uuid.uuid4()), codex))
        vault = _Vault(model, codex, secrets=(sign_in,))

        problems = await vault.problems(_spec(model_profile_id=str(model.id)))

        assert len(problems.messages) == 1
        assert "falls back to 'Ada's Codex'" in problems.messages[0]


class TestEveryModelARunReaches:
    async def test_capabilities_reviewers_and_specialists_are_refused_on_their_own_inputs(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        codex = _profile("Ada's Codex", secret=sign_in)
        vault = _Vault(codex, secrets=(sign_in,))
        pid = str(codex.id)

        problems = await vault.problems(
            _spec(
                reviewers=[{"name": "tone", "model_profile_id": pid}, {"name": "draft"}],
                capabilities=[
                    {"id": "browser_use", "config": {"step_model_profile_id": pid}},
                    {"id": "follow_ups", "config": {"model_profile_id": pid}},
                    {"id": "clock"},
                    {"id": "no_such_capability"},
                    {
                        "id": "subagents",
                        "config": {
                            "inline": [
                                {
                                    "name": "researcher",
                                    "description": "Looks things up",
                                    "instructions": "Find sources.",
                                    "model_profile_id": pid,
                                },
                                {
                                    "name": "writer",
                                    "description": "Writes it down",
                                    "instructions": "Write it up.",
                                },
                            ]
                        },
                    },
                ],
            )
        )

        # A capability's field is addressed inside its config, as the card's
        # generated form marks one (`capabilityConfigErrors`).
        assert [problem["field"] for problem in problems.fields] == [
            "reviewers.0.model_profile_id",
            "capabilities.browser_use.config.step_model_profile_id",
            "capabilities.follow_ups.config.model_profile_id",
            "specialists.researcher.model_profile_id",
        ]
        assert problems.messages[0].startswith("Reviewer 'tone': Model 'Ada's Codex'")
        assert problems.messages[1].startswith("Capability 'browser_use': Model")
        assert problems.messages[3].startswith("Specialist 'researcher': Model")

    async def test_a_model_no_run_reaches_is_not_refused(self):
        """Held to the spend rule, not wider: a switched-off capability's model and
        a specialist's capability models are never handed a run, so a sign-in there
        spends nobody's subscription. `validate_spec` still checks they exist."""
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        codex = _profile("Ada's Codex", secret=sign_in)
        vault = _Vault(codex, secrets=(sign_in,))
        pid = str(codex.id)

        problems = await vault.problems(
            _spec(
                capabilities=[
                    {
                        "id": "browser_use",
                        "enabled": False,
                        "config": {"step_model_profile_id": pid},
                    },
                    {"id": "follow_ups", "enabled": False, "config": {"model_profile_id": pid}},
                    {
                        "id": "subagents",
                        "config": {
                            "inline": [
                                {
                                    "name": "researcher",
                                    "description": "Looks things up",
                                    "instructions": "Find sources.",
                                    "capabilities": [
                                        {"id": "follow_ups", "config": {"model_profile_id": pid}}
                                    ],
                                }
                            ]
                        },
                    },
                ],
            )
        )

        assert problems.messages == []


class TestPromotion:
    async def test_a_version_on_a_sign_in_the_promoter_cannot_see_is_refused(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        codex = _profile("Ada's Codex", secret=sign_in)
        vault = _Vault(codex, secrets=(sign_in,))
        version = MagicMock(id=uuid.uuid4(), version=4)
        version.spec = {"name": "x", "model_profile_id": str(codex.id)}

        with vault.patched(), pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(MagicMock()).refuse_borrowed_sign_ins(_ctx(), version)

        assert refused.value.message == (
            "Version 4 runs on somebody's own ChatGPT sign-in, which you cannot use"
        )
        assert refused.value.details["version_id"] == version.id
        assert len(refused.value.details["problems"]) == 1

    async def test_a_version_on_a_sign_in_the_promoter_can_see_is_promoted(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        codex = _profile("My Codex", secret=sign_in)
        vault = _Vault(codex, secrets=(sign_in,), visible=(sign_in,))
        version = MagicMock()
        version.spec = {"name": "x", "model_profile_id": str(codex.id)}

        with vault.patched():
            await AgentRegistryService(MagicMock()).refuse_borrowed_sign_ins(_ctx(), version)
