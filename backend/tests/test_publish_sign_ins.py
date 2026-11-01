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
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities import load_builtins
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName, Perm
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

    def __init__(
        self,
        *profiles: MagicMock,
        secrets: tuple = (),
        visible: tuple = (),
        versions: tuple = (),
    ) -> None:
        self.profiles = {profile.id: profile for profile in profiles}
        self.secrets = {secret.id: secret for secret in secrets}
        self.visible = {secret.id for secret in visible}
        self.versions = {version.id: version for version in versions}
        self.access = AsyncMock(side_effect=self._may_see)

    async def _profiles(self, _db, ids, **_kwargs):
        return {pid: self.profiles[pid] for pid in ids if pid in self.profiles}

    async def _secrets(self, _db, ids, **_kwargs):
        return {sid: self.secrets[sid] for sid in ids if sid in self.secrets}

    async def _may_see(self, _db, _ctx, secret, *_args, **_kwargs) -> bool:
        return secret.id in self.visible

    async def _version(self, _db, version_id, **_kwargs):
        return self.versions.get(version_id)

    @contextmanager
    def patched(self) -> Iterator[None]:
        with (
            patch(f"{REGISTRY_PATH}.credential_repo.get_profiles_by_ids", new=self._profiles),
            patch(f"{REGISTRY_PATH}.organization_secret_repo.get_many", new=self._secrets),
            patch(f"{REGISTRY_PATH}.resolve_access", new=self.access),
            patch(f"{REGISTRY_PATH}.agent_repo.get_version", new=self._version),
        ):
            yield

    async def problems(self, spec: AgentSpec, ctx: AuthContext | None = None):
        with self.patched():
            return await AgentRegistryService(MagicMock())._sign_in_problems(ctx or _ctx(), spec)


def _spec(**fields) -> AgentSpec:
    return AgentSpec.model_validate({"name": "Helpdesk", **fields})


def _delegation(**config) -> dict:
    return {"id": "subagents", "config": config}


def _version(name: str, **fields) -> MagicMock:
    """A published version of a delegate, frozen as its own publisher left it."""
    version = MagicMock(id=uuid.uuid4(), agent_id=uuid.uuid4(), version=1)
    version.spec = {"name": name, **fields}
    return version


def _pin(version: MagicMock) -> dict:
    return {"agent_id": str(version.agent_id), "agent_version_id": str(version.id)}


def _specialist(name: str, **fields) -> dict:
    return {"name": name, "description": "Helps", "instructions": "Help.", **fields}


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
                # Follow-ups with no model of its own does not run, so it names none.
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


class TestPinnedDelegates:
    """A run resolves a pinned delegate's model for its own caller, so a pin is
    a choice of what a run spends as much as naming a model is."""

    async def test_a_delegate_on_a_sign_in_the_publisher_cannot_see_is_refused_on_the_pin(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        codex = _profile("Ada's Codex", secret=sign_in)
        research = _version("Research", model_profile_id=str(codex.id))
        vault = _Vault(codex, secrets=(sign_in,), versions=(research,))

        problems = await vault.problems(
            _spec(capabilities=[_delegation()], subagents=[_pin(research)])
        )

        message = (
            "Delegate 'Research': Model 'Ada's Codex' runs on somebody's own ChatGPT "
            "sign-in, which you cannot use - pin another delegate or version, or ask its "
            "owner to share the sign-in with you"
        )
        assert problems.fields == [{"field": "subagents.0.agent_version_id", "message": message}]

    @pytest.mark.parametrize("auxiliary", ["reviewer", "browser", "follow_ups"])
    @pytest.mark.parametrize("max_depth", [1, 2])
    async def test_a_pinned_delegates_auxiliary_sign_in_is_judged_without_dynamic_specialists(
        self, auxiliary: str, max_depth: int
    ) -> None:
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        key = _secret(SecretKind.API_KEY)
        codex = _profile("Ada's Codex", secret=sign_in)
        gpt = _profile("GPT", secret=key)
        pid = str(codex.id)
        research = _version(
            "Research",
            model_profile_id=str(gpt.id),
            reviewers=[{"name": "tone", "model_profile_id": pid}]
            if auxiliary == "reviewer"
            else [],
            capabilities=(
                [{"id": "browser_use", "config": {"step_model_profile_id": pid}}]
                if auxiliary == "browser"
                else [{"id": "follow_ups", "config": {"model_profile_id": pid}}]
                if auxiliary == "follow_ups"
                else []
            ),
        )
        vault = _Vault(gpt, codex, secrets=(sign_in, key), versions=(research,))
        problems = await vault.problems(
            _spec(capabilities=[_delegation(max_depth=max_depth)], subagents=[_pin(research)])
        )
        assert len(problems.messages) == 1
        assert problems.fields[0]["field"] == "subagents.0.agent_version_id"
        assert problems.messages[0].startswith("Delegate 'Research': Model 'Ada's Codex'")

    async def test_a_delegate_falling_back_to_a_sign_in_is_refused(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        key = _secret(SecretKind.API_KEY)
        codex = _profile("Ada's Codex", secret=sign_in)
        gpt = _profile("GPT", secret=key, fallbacks=(codex,))
        research = _version("Research", model_profile_id=str(gpt.id))
        vault = _Vault(gpt, codex, secrets=(sign_in, key), versions=(research,))

        problems = await vault.problems(
            _spec(capabilities=[_delegation()], subagents=[_pin(research)])
        )

        assert problems.messages == [
            "Delegate 'Research': Model 'GPT' falls back to 'Ada's Codex', which runs on "
            "somebody's own ChatGPT sign-in you cannot use - pin another delegate or "
            "version, or ask its owner to share the sign-in with you"
        ]

    async def test_a_delegate_on_a_sign_in_the_publisher_can_see_is_allowed(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        codex = _profile("My Codex", secret=sign_in)
        research = _version("Research", model_profile_id=str(codex.id))
        vault = _Vault(codex, secrets=(sign_in,), visible=(sign_in,), versions=(research,))

        problems = await vault.problems(
            _spec(capabilities=[_delegation()], subagents=[_pin(research)])
        )

        assert problems.messages == []

    async def test_nested_delegates_are_followed_as_deep_as_the_run_goes(self):
        """`max_depth=2` on the parent leaves the delegate one level: its own
        specialists and pins run, and are named by the chain that reaches them."""
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        key = _secret(SecretKind.API_KEY)
        codex = _profile("Ada's Codex", secret=sign_in)
        gpt = _profile("GPT", secret=key)
        deep = _version("Deep", model_profile_id=str(codex.id))
        research = _version(
            "Research",
            model_profile_id=str(gpt.id),
            capabilities=[
                _delegation(
                    max_depth=3,
                    inline=[_specialist("reader", model_profile_id=str(codex.id))],
                )
            ],
            subagents=[_pin(deep)],
        )
        vault = _Vault(gpt, codex, secrets=(sign_in, key), versions=(research, deep))

        problems = await vault.problems(
            _spec(capabilities=[_delegation(max_depth=2)], subagents=[_pin(research)])
        )

        assert [problem["field"] for problem in problems.fields] == [
            "subagents.0.agent_version_id",
            "subagents.0.agent_version_id",
        ]
        assert problems.messages[0].startswith("Delegate 'Research': Model 'Ada's Codex'")
        assert problems.messages[1].startswith("Delegate 'Research -> Deep': Model 'Ada's Codex'")

    async def test_what_lies_past_the_depth_bound_is_not_judged(self):
        """At `max_depth=1` the delegate is built without delegation, so neither
        its specialists, its pins nor a catalog of its own reach anything."""
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        key = _secret(SecretKind.API_KEY)
        codex = _profile("Ada's Codex", secret=sign_in)
        gpt = _profile("GPT", secret=key)
        deep = _version("Deep", model_profile_id=str(codex.id))
        research = _version(
            "Research",
            model_profile_id=str(gpt.id),
            capabilities=[
                _delegation(
                    allow_dynamic=True,
                    inline=[_specialist("reader", model_profile_id=str(codex.id))],
                )
            ],
            subagents=[_pin(deep)],
        )
        vault = _Vault(gpt, codex, secrets=(sign_in, key), versions=(research, deep))

        problems = await vault.problems(
            _spec(capabilities=[_delegation()], subagents=[_pin(research)])
        )

        assert problems.messages == []

    async def test_a_delegate_that_invents_specialists_offers_every_model_it_names(self):
        """Its catalog may hand a dynamic specialist any model its own spec names
        (`models_a_run_reaches`), a reviewer's included."""
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        key = _secret(SecretKind.API_KEY)
        codex = _profile("Ada's Codex", secret=sign_in)
        gpt = _profile("GPT", secret=key)
        research = _version(
            "Research",
            model_profile_id=str(gpt.id),
            reviewers=[{"name": "tone", "model_profile_id": str(codex.id)}],
            capabilities=[_delegation(allow_dynamic=True)],
        )
        vault = _Vault(gpt, codex, secrets=(sign_in, key), versions=(research,))

        problems = await vault.problems(
            _spec(capabilities=[_delegation(max_depth=2)], subagents=[_pin(research)])
        )

        assert len(problems.messages) == 1
        assert problems.messages[0].startswith("Delegate 'Research': Model 'Ada's Codex'")

    async def test_a_pin_nothing_delegates_through_or_that_is_gone_asks_nothing(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        codex = _profile("Ada's Codex", secret=sign_in)
        research = _version("Research", model_profile_id=str(codex.id))
        gone = _version("Gone")
        vault = _Vault(codex, secrets=(sign_in,), versions=(research,))

        switched_off = await vault.problems(
            _spec(
                capabilities=[{"id": "subagents", "enabled": False}],
                subagents=[_pin(research)],
            )
        )
        missing = await vault.problems(_spec(capabilities=[_delegation()], subagents=[_pin(gone)]))

        assert switched_off.messages == []
        assert missing.messages == []

    async def test_a_delegate_reached_twice_is_judged_once_and_a_gone_one_skipped(self):
        """A diamond - two of Research's delegates pin Deep - reaches Deep twice at
        the same depth; it is walked once."""
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        key = _secret(SecretKind.API_KEY)
        codex = _profile("Ada's Codex", secret=sign_in)
        gpt = _profile("GPT", secret=key)
        deep = _version("Deep", model_profile_id=str(codex.id))
        middles = [
            _version(
                name,
                model_profile_id=str(gpt.id),
                capabilities=[_delegation(max_depth=2)],
                subagents=[_pin(deep)],
            )
            for name in ("Left", "Right")
        ]
        research = _version(
            "Research",
            model_profile_id=str(gpt.id),
            capabilities=[_delegation(max_depth=3)],
            subagents=[*(_pin(middle) for middle in middles), _pin(_version("Gone"))],
        )
        vault = _Vault(gpt, codex, secrets=(sign_in, key), versions=(research, deep, *middles))

        problems = await vault.problems(
            _spec(capabilities=[_delegation(max_depth=3)], subagents=[_pin(research)])
        )

        assert len(problems.messages) == 1
        assert "-> Deep': Model 'Ada's Codex'" in problems.messages[0]

    async def test_a_delegation_loop_in_stored_versions_ends(self):
        """Pinning cannot name a version published later, but stored data is not
        bound by that; the depth left shrinks at every level, so the walk ends."""
        key = _secret(SecretKind.API_KEY)
        gpt = _profile("GPT", secret=key)
        loop = _version("Loop", model_profile_id=str(gpt.id))
        loop.spec["capabilities"] = [_delegation(max_depth=3)]
        loop.spec["subagents"] = [_pin(loop)]
        vault = _Vault(gpt, secrets=(key,), versions=(loop,))

        problems = await vault.problems(
            _spec(capabilities=[_delegation(max_depth=3)], subagents=[_pin(loop)])
        )

        assert problems.messages == []


class TestApiKeys:
    """A run under an API key spends no sign-in (`ModelProfileService.resolve`),
    so a key may not point an agent at one either - whatever its issuer sees."""

    async def test_a_key_is_refused_a_sign_in_its_issuer_can_see(self):
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        codex = _profile("Ada's Codex", secret=sign_in)
        vault = _Vault(codex, secrets=(sign_in,), visible=(sign_in,))
        key = replace(
            _ctx(),
            api_key_id=uuid.uuid4(),
            key_scopes=frozenset({Perm.AGENTS_PUBLISH, Perm.SECRETS_VIEW}),
        )

        problems = await vault.problems(_spec(model_profile_id=str(codex.id)), key)

        assert problems.fields == [
            {
                "field": "model_profile_id",
                "message": (
                    "Model 'Ada's Codex' runs on somebody's own ChatGPT sign-in, which an "
                    "API key cannot use - pick another model"
                ),
            }
        ]
        vault.access.assert_not_awaited()

    async def test_a_persisted_key_context_is_still_a_key(self):
        """A key's scope ceiling without its live id is still nobody's session."""
        sign_in = _secret(SecretKind.OPENAI_CODEX)
        key = _secret(SecretKind.API_KEY)
        codex = _profile("Ada's Codex", secret=sign_in)
        gpt = _profile("GPT", secret=key, fallbacks=(codex,))
        vault = _Vault(gpt, codex, secrets=(sign_in, key), visible=(sign_in,))
        scoped = replace(_ctx(), key_scopes=frozenset({Perm.AGENTS_PUBLISH}))

        problems = await vault.problems(_spec(model_profile_id=str(gpt.id)), scoped)

        assert problems.messages == [
            "Model 'GPT' falls back to 'Ada's Codex', which runs on somebody's own ChatGPT "
            "sign-in an API key cannot use - remove it from the fallbacks"
        ]

    async def test_a_key_may_still_publish_on_an_ordinary_key(self):
        key = _secret(SecretKind.API_KEY)
        gpt = _profile("GPT", secret=key)
        vault = _Vault(gpt, secrets=(key,))
        scoped = replace(_ctx(), api_key_id=uuid.uuid4(), key_scopes=frozenset())

        problems = await vault.problems(_spec(model_profile_id=str(gpt.id)), scoped)

        assert problems.messages == []
