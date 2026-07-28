"""A capability declares that it needs a secret; a binding says which one.

The whole design of the secret store is in this handshake, and every test here
is one half of it. Code declares a *kind*; configuration names an *instance*;
the plaintext is unsealed at build time, reaches the capability object, and goes
no further - not into ``AgentDeps``, not into a tool argument, not into the
model's context, not into a log line.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities import (
    REGISTRY,
    CapabilityBinding,
    CapabilityBuildContext,
    build,
    register,
)
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, AwsCredentialsSecret, SecretKind, SecretRequirement
from app.db.models.resource_grant import GrantLevel, Visibility
from app.services.agent_registry import AgentRegistryService

CAPABILITY_ID = "test_needs_a_key"


class _Weather(AbstractCapability[None]):
    """A stand-in for a client capability calling an authenticated third-party API."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key


@pytest.fixture
def capability_needing_a_key() -> Iterator[None]:
    """Register a capability that declares a secret, and take it away again.

    A fixture rather than a builtin because no shipped capability needs a
    credential yet - the store exists for the ones a client writes - and the
    handshake has to be tested before the first one is written, not after.
    """

    @register(
        id=CAPABILITY_ID,
        name="Weather",
        category="test",
        description="Calls a weather API",
        tools=(),
        secret=SecretRequirement(kind=SecretKind.API_KEY, description="Weather API key"),
    )
    def _build(ctx: CapabilityBuildContext) -> _Weather:
        assert isinstance(ctx.secret, ApiKeySecret)
        return _Weather(api_key=ctx.secret.api_key.get_secret_value())

    yield
    REGISTRY.pop(CAPABILITY_ID, None)


@pytest.mark.usefixtures("capability_needing_a_key")
class TestInjection:
    def test_the_referenced_secret_reaches_the_capability_instance(self):
        secret_id = uuid.uuid4()

        built = build(
            [CapabilityBinding(capability_id=CAPABILITY_ID, secret_id=secret_id)],
            secrets={secret_id: ApiKeySecret(api_key="wx-live-4242")},
        )

        assert isinstance(built[0], _Weather)
        assert built[0].api_key == "wx-live-4242"

    def test_a_secret_deleted_after_publish_refuses_the_build(self):
        """Publish already refused a missing reference, so this is the later case.

        Degrading instead would produce an agent that answers as though the API
        had said no, which is worse than a run that stops and says why.
        """
        secret_id = uuid.uuid4()

        with pytest.raises(BadRequestError) as refused:
            build([CapabilityBinding(capability_id=CAPABILITY_ID, secret_id=secret_id)], secrets={})

        assert refused.value.details == {
            "capability_id": CAPABILITY_ID,
            "secret_id": str(secret_id),
            "required_kind": "api_key",
        }

    def test_a_binding_with_no_reference_at_all_is_refused(self):
        with pytest.raises(BadRequestError) as refused:
            build([CapabilityBinding(capability_id=CAPABILITY_ID)], secrets={})

        assert refused.value.details is not None
        assert refused.value.details["secret_id"] is None

    def test_a_capability_that_needs_nothing_is_handed_nothing(self):
        """`clock` declares no secret, so its context must not carry one."""
        seen: list[CapabilityBuildContext] = []

        @register(
            id="test_needs_nothing",
            name="Nothing",
            category="test",
            description="",
            tools=(),
        )
        def _build(ctx: CapabilityBuildContext) -> None:
            seen.append(ctx)
            return

        try:
            build(
                [CapabilityBinding(capability_id="test_needs_nothing", secret_id=uuid.uuid4())],
                secrets={uuid.uuid4(): ApiKeySecret(api_key="wx")},
            )
        finally:
            REGISTRY.pop("test_needs_nothing", None)

        assert seen[0].secret is None

    def test_a_build_context_masks_the_secret_in_a_repr(self):
        """The way a plaintext escapes is a dataclass reaching a log line."""
        context = CapabilityBuildContext(
            binding=CapabilityBinding(capability_id=CAPABILITY_ID),
            config=None,
            secret=ApiKeySecret(api_key="wx-live-do-not-print"),
        )
        assert "wx-live-do-not-print" not in repr(context)

    def test_nothing_about_the_secret_reaches_a_log_line(self, caplog):
        secret_id = uuid.uuid4()
        with caplog.at_level(logging.DEBUG):
            build(
                [CapabilityBinding(capability_id=CAPABILITY_ID, secret_id=secret_id)],
                secrets={secret_id: ApiKeySecret(api_key="wx-live-4242")},
            )
        assert "wx-live-4242" not in caplog.text


@pytest.fixture
def secret_row() -> MagicMock:
    """A stored secret of the kind the test capability asks for."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.name = "Weather API"
    row.kind = SecretKind.API_KEY.value
    return row


async def _publish_problems(binding: CapabilityBindingSpec, *, secret: MagicMock | None) -> Any:
    """Validate a spec carrying one binding, and report what publish refused.

    Driven through the public entry point rather than the private helper: the
    behaviour worth guarding is "publish refuses", and a spec that validates by
    a different route later would still have to.
    """
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
    if secret is not None:
        # Stamped here rather than in the fixture: the lookup that produced this
        # row is org-scoped, so anything it returns belongs to the caller's
        # organization by construction. Publish now also asks whether the
        # publisher may *reach* it, and that check starts with the tenant.
        secret.organization_id = ctx.organization_id
    spec = AgentSpec(name="Forecast", model_profile_id=uuid.uuid4(), capabilities=[binding])
    lookup = AsyncMock(return_value=secret)
    with (
        patch(
            "app.services.agent_registry.credential_repo.get_profile",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch("app.services.agent_registry.organization_secret_repo.get", new=lookup),
    ):
        try:
            await AgentRegistryService(MagicMock()).validate_spec(ctx, spec)
        except BadRequestError as refused:
            assert refused.details is not None
            return refused.details["problems"], lookup, ctx
    return [], lookup, ctx


@pytest.mark.usefixtures("capability_needing_a_key")
class TestPublishValidation:
    """A broken reference is refused while somebody is looking at a form."""

    @pytest.mark.anyio
    async def test_a_capability_needing_a_secret_with_none_selected_is_refused(self):
        problems, _, _ = await _publish_problems(
            CapabilityBindingSpec(id=CAPABILITY_ID), secret=None
        )
        assert problems == [
            f"Capability '{CAPABILITY_ID}' needs a api_key secret "
            "(Weather API key) and none is selected"
        ]

    @pytest.mark.anyio
    async def test_a_reference_to_a_secret_this_organization_does_not_have_is_refused(self):
        secret_id = uuid.uuid4()

        problems, lookup, ctx = await _publish_problems(
            CapabilityBindingSpec(id=CAPABILITY_ID, secret_id=secret_id), secret=None
        )

        assert problems == [
            f"Capability '{CAPABILITY_ID}' points at a secret this organization does not "
            f"have: {secret_id}"
        ]
        # Scoped, so a secret belonging to another tenant is indistinguishable
        # from one that does not exist.
        assert lookup.call_args.kwargs["organization_id"] == ctx.organization_id

    @pytest.mark.anyio
    async def test_a_secret_of_the_wrong_shape_is_refused(self, secret_row):
        secret_row.kind = SecretKind.AWS_CREDENTIALS.value
        secret_row.name = "Bedrock"

        problems, _, _ = await _publish_problems(
            CapabilityBindingSpec(id=CAPABILITY_ID, secret_id=secret_row.id), secret=secret_row
        )

        assert problems == [
            f"Capability '{CAPABILITY_ID}' needs a api_key secret, but "
            "'Bedrock' holds a aws_credentials"
        ]

    @pytest.mark.anyio
    async def test_a_matching_secret_publishes(self, secret_row):
        problems, _, _ = await _publish_problems(
            CapabilityBindingSpec(id=CAPABILITY_ID, secret_id=secret_row.id), secret=secret_row
        )
        assert problems == []

    @pytest.mark.anyio
    async def test_a_key_the_publisher_cannot_reach_is_refused(self, secret_row):
        """Binding a key is lending it: the agent runs it for everyone who can
        run the agent. The picker only offers what the publisher can see, but the
        API takes an id - and an id is guessable in a way a list is not.

        Refused in the same words as a missing one, so the difference between
        "no such key" and "not yours" cannot be used to enumerate the vault.
        """
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER
        )
        secret_row.organization_id = ctx.organization_id
        secret_row.owner_user_id = uuid.uuid4()
        secret_row.visibility = Visibility.PRIVATE.value
        spec = AgentSpec(
            name="Forecast",
            model_profile_id=uuid.uuid4(),
            capabilities=[CapabilityBindingSpec(id=CAPABILITY_ID, secret_id=secret_row.id)],
        )

        with (
            patch(
                "app.services.agent_registry.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.services.agent_registry.organization_secret_repo.get",
                new=AsyncMock(return_value=secret_row),
            ),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(BadRequestError) as refused,
        ):
            await AgentRegistryService(MagicMock()).validate_spec(ctx, spec)

        assert refused.value.details is not None
        assert refused.value.details["problems"] == [
            f"Capability '{CAPABILITY_ID}' points at a secret this organization does not "
            f"have: {secret_row.id}"
        ]

    @pytest.mark.anyio
    async def test_a_key_shared_with_the_publisher_publishes(self, secret_row):
        """The other half: a grant is what sharing writes, and it has to be
        enough - otherwise the sharing panel promises access publish refuses."""
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER
        )
        secret_row.organization_id = ctx.organization_id
        secret_row.owner_user_id = uuid.uuid4()
        secret_row.visibility = Visibility.PRIVATE.value
        spec = AgentSpec(
            name="Forecast",
            model_profile_id=uuid.uuid4(),
            capabilities=[CapabilityBindingSpec(id=CAPABILITY_ID, secret_id=secret_row.id)],
        )

        with (
            patch(
                "app.services.agent_registry.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.services.agent_registry.organization_secret_repo.get",
                new=AsyncMock(return_value=secret_row),
            ),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=GrantLevel.READ),
            ),
        ):
            await AgentRegistryService(MagicMock()).validate_spec(ctx, spec)

    @pytest.mark.anyio
    async def test_a_reference_nothing_consumes_is_refused(self):
        """The failure nobody would ever notice: configured, stored, never read.

        `clock` takes no secret, so a secret chosen for it reads as protection
        that is not there.
        """
        problems, _, _ = await _publish_problems(
            CapabilityBindingSpec(id="clock", secret_id=uuid.uuid4()), secret=None
        )
        assert problems == [
            "Capability 'clock' does not use a secret, so the one selected here "
            "would be stored and never read"
        ]


class TestSpecCarriesOnlyAReference:
    def test_a_binding_stores_an_id_and_nothing_else(self):
        """A spec is exported to a client's git repository."""
        secret_id = uuid.uuid4()
        binding = CapabilityBindingSpec(id=CAPABILITY_ID, secret_id=secret_id)

        assert binding.to_binding().secret_id == secret_id
        assert "secret" not in binding.model_dump(exclude={"secret_id"})

    def test_a_spec_written_before_secrets_existed_still_loads(self):
        """Additive evolution: a version-4 binding has no key and means "none"."""
        assert CapabilityBindingSpec(id="clock").secret_id is None

    def test_a_value_cannot_be_smuggled_into_a_binding(self):
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            CapabilityBindingSpec(
                id=CAPABILITY_ID,
                secret=AwsCredentialsSecret,  # type: ignore[call-arg]
            )
