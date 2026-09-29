"""The refusals a node makes before it reaches anything: configs, guards, narrowings.

A graph that passed validation never reaches most of these - the dispatcher hands a
handler exactly the config and input its schemas validated - so they are proved
here directly rather than through a run that could not produce them.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, HttpCredentialSecret, seal_secret, unseal_kind
from app.core.vault import VaultScope
from app.workflows.contracts.results import Failed
from app.workflows.nodes._http import is_http_url
from app.workflows.nodes.agent_run import AgentRunConfig
from app.workflows.nodes.agent_run import _handler as agent_node
from app.workflows.nodes.http_request import HttpAuth, HttpRequestConfig
from app.workflows.nodes.http_request import _handler as http_node
from app.workflows.nodes.knowledge_search import _handler as search_node
from app.workflows.nodes.notification_send import _handler as notify_node

pytestmark = pytest.mark.anyio


class _Other(BaseModel):
    """A config of some other node - what a guard is there to turn away."""


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")


@pytest.mark.parametrize(
    "check",
    [
        agent_node.check_resources,
        http_node.check_resources,
        search_node.check_resources,
        notify_node.check_resources,
    ],
    ids=["agent.run", "http.request", "knowledge.search", "notification.send"],
)
async def test_a_resource_check_handed_another_nodes_config_has_nothing_to_say(check):
    assert await check(MagicMock(), _ctx(), _Other()) == []


@pytest.mark.parametrize(
    ("handle", "code"),
    [
        (http_node.handle, "REQUEST_NOT_CONFIGURED"),
        (search_node.handle, "SEARCH_NOT_CONFIGURED"),
        (notify_node.handle, "NOTIFICATION_NOT_CONFIGURED"),
    ],
)
async def test_a_handler_with_no_config_fails_rather_than_guessing(handle, code):
    result = await handle(None, None)
    assert isinstance(result, Failed) and result.error.code == code


class TestHttpConfig:
    async def test_a_step_without_a_credential_has_no_secret_to_check(self):
        assert (
            await http_node.check_resources(
                MagicMock(), _ctx(), HttpRequestConfig(url="https://a.example")
            )
            == []
        )

    def test_a_credential_cannot_travel_in_a_header_the_transport_owns(self):
        with pytest.raises(ValidationError, match="cannot carry a credential"):
            HttpAuth(kind="header", secret_id=uuid.uuid4(), header_name="Cookie")

    @pytest.mark.parametrize(
        ("headers", "message"),
        [
            ({"bad name": "x"}, "not a header name"),
            ({"Host": "evil"}, "cannot be set here"),
            ({"X-A": "one\ntwo"}, "spans lines"),
            ({"X-A": "x" * 1025}, "too long"),
        ],
    )
    def test_a_header_that_is_not_ours_to_send_is_refused(self, headers, message):
        with pytest.raises(ValidationError, match=message):
            HttpRequestConfig(url="https://a.example", headers=headers)

    def test_a_url_the_parser_cannot_read_is_not_an_http_url(self):
        assert is_http_url("http://[::1") is False


class TestNotificationRecipients:
    async def test_a_run_whose_workflow_is_gone_may_tell_nobody(self):
        assert await notify_node._permitted(MagicMock(), uuid.uuid4(), None, (uuid.uuid4(),)) == []

    async def test_a_recipient_who_left_is_dropped(self):
        workflow = SimpleNamespace(id=uuid.uuid4())
        with (
            patch.object(notify_node.workflow_repo, "get", new=AsyncMock(return_value=workflow)),
            patch.object(notify_node.member_repo, "get_active", new=AsyncMock(return_value=None)),
        ):
            permitted = await notify_node._permitted(
                MagicMock(), uuid.uuid4(), workflow.id, (uuid.uuid4(),)
            )
        assert permitted == []


class TestAgentRunConfig:
    def test_no_schema_given_is_no_schema_required(self):
        config = AgentRunConfig.model_validate(
            {
                "agent": {"agent_id": str(uuid.uuid4()), "version_id": str(uuid.uuid4())},
                "structured_output_schema": None,
            }
        )
        assert config.structured_output_schema is None

    @pytest.mark.parametrize(("cost", "expected"), [(None, Decimal(0)), ("0.25", Decimal("0.25"))])
    async def test_what_a_parked_run_had_spent_is_read_off_its_row(self, cost, expected):
        run = None if cost is None else SimpleNamespace(cost_usd=Decimal(cost))
        with patch.object(agent_node.agent_run_repo, "get_run", new=AsyncMock(return_value=run)):
            spent = await agent_node._cost_so_far(MagicMock(), uuid.uuid4(), uuid.uuid4())
        assert spent == expected


@pytest.mark.security
def test_an_envelope_that_is_not_the_kind_asked_for_is_refused_without_its_content():
    scope = VaultScope.organization(uuid.uuid4())
    sealed = seal_secret(
        HttpCredentialSecret(token="tok-abcdef-123456", origins=("https://a.example",)),
        scope=scope,
    )

    with pytest.raises(BadRequestError) as refused:
        unseal_kind(
            sealed.ciphertext, model=ApiKeySecret, scope=scope, key_version=sealed.key_version
        )
    assert "tok-abcdef" not in str(refused.value.details)
