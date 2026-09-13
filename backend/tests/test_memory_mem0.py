"""Tests for the mem0 memory capability.

Two things are worth guarding, and neither is "does the SDK work". The first is
**isolation on the wire**: mem0's `user_id` is the whole scope namespace, so a
test that asserted our call to the SDK rather than the namespace it was given
would prove nothing about whether two organizations can see each other's
memories. The second is the **adapter**, which exists because the SDK's async
client makes a blocking network call from its constructor - so the client must be
built once, off the loop, and never on a host this deployment has not allowed.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.audience import RunAudience
from app.agents.capabilities import build
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.memory_mem0 import (
    MemoryMem0,
    MemoryMem0Config,
    _build,
)
from app.agents.capabilities.memory_mem0 import _client as client_module
from app.agents.capabilities.memory_mem0._client import Mem0Fact, _hits, namespace
from app.agents.capabilities.memory_mem0._toolset import _NO_STORE, Mem0Toolset
from app.agents.deps import AgentDeps
from app.core.exceptions import ExternalServiceError
from app.core.secret_kinds import ApiKeySecret

pytestmark = pytest.mark.anyio

_REAL_CONSTRUCT = client_module._construct
"""Captured before the autouse guard replaces it, for the one test that needs it."""

ORG = uuid4()
AGENT = uuid4()
PERSON = uuid4()
PERSON_KEY = f"person:{PERSON}"
ROOM = "room:slack:C1"


def _deps(*, person=None, room=None) -> AgentDeps:
    return AgentDeps(
        organization_id=ORG,
        agent_id=AGENT,
        audience=RunAudience(user_id=person, room_key=room),
    )


def _ctx(deps: AgentDeps) -> RunContext[AgentDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), retry=0, max_retries=1)


def _toolset(*, allow_personal: bool = True) -> Mem0Toolset:
    return Mem0Toolset(api_key="k-1", base_url=None, allow_personal=allow_personal)


@pytest.fixture(autouse=True)
def _no_real_mem0(monkeypatch):
    """No test here may reach the network, and the cache starts empty.

    The SDK's constructor pings `api.mem0.ai` for real, so a test that forgets to
    patch `_construct` does not fail - it dials out and fails on a 401 from
    somebody else's service. This makes that a loud local error instead, and the
    cache is cleared because it is process-wide: a client built in one test would
    otherwise be handed to the next.
    """
    client_module._clients.clear()

    def _refuse(*_args, **_kwargs):
        raise AssertionError("a mem0 test reached the network; patch `_construct`")

    monkeypatch.setattr(client_module, "_construct", _refuse)
    yield
    client_module._clients.clear()


class TestNamespace:
    """mem0's `user_id` is the whole isolation boundary - one account, many tenants."""

    def test_it_separates_a_person_from_a_room(self):
        person = namespace(ORG, AGENT, PERSON_KEY)
        room = namespace(ORG, AGENT, ROOM)

        assert person == f"{ORG}:{AGENT}:{PERSON_KEY}"
        assert person != room

    def test_it_separates_two_organizations_holding_the_same_agent_id(self):
        assert namespace(uuid4(), AGENT, PERSON_KEY) != namespace(uuid4(), AGENT, PERSON_KEY)

    def test_it_separates_two_agents_in_one_organization(self):
        assert namespace(ORG, uuid4(), PERSON_KEY) != namespace(ORG, uuid4(), PERSON_KEY)

    def test_there_is_no_shared_bucket_to_fall_back_to(self):
        """`owner_key` is required. A default would be one namespace every
        anonymous visitor wrote into and every run read - which is the
        organization-wide store this design removed (#1470)."""
        with pytest.raises(TypeError):
            namespace(ORG, AGENT)  # ty: ignore[missing-argument]


class TestAllowlist:
    """The key travels in an `Authorization` header, so a builder who may bind but
    not read a shared key must not be able to point it at their own server."""

    async def test_the_managed_cloud_needs_no_entry(self, monkeypatch):
        monkeypatch.setattr(client_module.settings, "MEM0_ALLOWED_HOSTS", [])
        with patch.object(client_module, "_construct", return_value=MagicMock()):
            assert await client_module._client("k", None) is not None

    async def test_an_unlisted_self_hosted_host_is_refused(self, monkeypatch):
        monkeypatch.setattr(client_module.settings, "MEM0_ALLOWED_HOSTS", ["mem0.internal"])
        with pytest.raises(ExternalServiceError):
            await client_module._client("k", "https://attacker.example")

    async def test_an_empty_allowlist_refuses_self_hosted_outright(self, monkeypatch):
        monkeypatch.setattr(client_module.settings, "MEM0_ALLOWED_HOSTS", [])
        with pytest.raises(ExternalServiceError):
            await client_module._client("k", "https://mem0.internal")

    async def test_a_listed_host_is_allowed(self, monkeypatch):
        monkeypatch.setattr(client_module.settings, "MEM0_ALLOWED_HOSTS", ["mem0.internal"])
        with patch.object(client_module, "_construct", return_value=MagicMock()):
            assert await client_module._client("k", "https://mem0.internal") is not None

    async def test_plain_http_is_refused_even_when_the_host_is_listed(self, monkeypatch):
        monkeypatch.setattr(client_module.settings, "MEM0_ALLOWED_HOSTS", ["mem0.internal"])
        with pytest.raises(ExternalServiceError):
            await client_module._client("k", "http://mem0.internal")

    async def test_a_refusal_does_not_repeat_the_url(self):
        """A host - and anything in its query string - must not reach a message
        that is logged (#342)."""
        with pytest.raises(ExternalServiceError) as excinfo:
            await client_module._client("k", "https://secret-host.example?token=abc")
        assert "secret-host" not in str(excinfo.value.message)
        assert "abc" not in str(excinfo.value.details)


class TestClientConstruction:
    """The SDK's async client runs a blocking `requests.get` from `__init__`, so it
    is built once per credential in a worker thread rather than per call on the
    loop (checked against mem0ai 2.0.20)."""

    async def test_the_client_is_built_once_per_credential(self):
        with patch.object(
            client_module, "_construct", side_effect=lambda *_: MagicMock()
        ) as construct:
            first = await client_module._client("k", None)
            second = await client_module._client("k", None)
        assert first is second
        assert construct.call_count == 1

    async def test_two_credentials_do_not_share_a_client(self):
        with patch.object(client_module, "_construct", side_effect=lambda *_: MagicMock()):
            assert await client_module._client("k-1", None) is not await client_module._client(
                "k-2", None
            )

    async def test_concurrent_first_calls_all_get_one_client(self):
        """Nothing is locked across the construction, on purpose: the SDK's ping has
        no timeout, so a process-wide lock held across it would turn one unreachable
        mem0 into every run in the process waiting on the same lock. Cold callers may
        each build one; `setdefault` then hands them all the same instance and the
        losers are dropped."""
        with patch.object(client_module, "_construct", side_effect=lambda *_: MagicMock()):
            clients = await asyncio.gather(*(client_module._client("k", None) for _ in range(5)))
        assert len({id(client) for client in clients}) == 1
        assert client_module._clients[("k", None)] is clients[0]

    async def test_a_mem0_that_never_answers_is_a_refusal_rather_than_a_held_run(self, monkeypatch):
        """The SDK sets no timeout on its ping, so an unreachable mem0 would hold the
        run for as long as the socket does. Bounded here, since it is not there."""
        monkeypatch.setattr(client_module, "_CONNECT_TIMEOUT", 0.01)

        def _hang(*_args, **_kwargs):
            time.sleep(5)

        with (
            patch.object(client_module, "_construct", _hang),
            pytest.raises(ExternalServiceError),
        ):
            await client_module._client("k", None)

    async def test_a_failure_to_connect_is_a_refusal_not_a_crashed_run(self, monkeypatch):
        """The real `_construct`, against an SDK that raises: a bad key or an
        unreachable host must be a refusal the model reads, not a crashed run."""
        monkeypatch.setattr(client_module, "_construct", _REAL_CONSTRUCT)
        with (
            patch.object(client_module, "AsyncMemoryClient", side_effect=RuntimeError("nope")),
            pytest.raises(ExternalServiceError),
        ):
            await client_module._client("k", None)


class TestTheWire:
    """What reaches mem0, and what a failure from it becomes.

    The namespace assertions are the isolation guarantee: a test that checked we
    called `add` would prove nothing about whether one tenant can reach another's
    memories.
    """

    @staticmethod
    def _client(**behaviour) -> MagicMock:
        client = MagicMock()
        client.add = AsyncMock(**behaviour)
        client.search = AsyncMock(**behaviour)
        return client

    async def test_remember_sends_the_owners_namespace_and_nothing_wider(self):
        client = self._client(return_value={})
        with patch.object(client_module, "_client", AsyncMock(return_value=client)):
            await client_module.mem0_remember(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                owner_key=PERSON_KEY,
                content="likes tea",
            )
        assert client.add.await_args.kwargs["user_id"] == f"{ORG}:{AGENT}:{PERSON_KEY}"

    async def test_a_failed_remember_is_a_refusal_that_names_no_upstream_text(self):
        """A client error can echo the request, and a URL carries a key in its
        query string, so the upstream text goes to the log and never here (#342)."""
        client = self._client(side_effect=RuntimeError("token=sk-secret leaked"))
        with (
            patch.object(client_module, "_client", AsyncMock(return_value=client)),
            pytest.raises(ExternalServiceError) as excinfo,
        ):
            await client_module.mem0_remember(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                owner_key=PERSON_KEY,
                content="x",
            )
        assert "sk-secret" not in str(excinfo.value.message)
        assert "sk-secret" not in str(excinfo.value.details)

    async def test_search_sends_the_owners_namespace(self):
        client = self._client(return_value={"results": [{"memory": "a"}]})
        with patch.object(client_module, "_client", AsyncMock(return_value=client)):
            hits = await client_module.mem0_recall(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                owner_key=ROOM,
                query="q",
                limit=3,
            )
        assert [hit.content for hit in hits] == ["a"]
        assert client.search.await_args.kwargs["user_id"] == f"{ORG}:{AGENT}:{ROOM}"

    async def test_a_failed_search_is_a_refusal_not_a_crashed_run(self):
        client = self._client(side_effect=RuntimeError("boom"))
        with (
            patch.object(client_module, "_client", AsyncMock(return_value=client)),
            pytest.raises(ExternalServiceError),
        ):
            await client_module.mem0_recall(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                owner_key=PERSON_KEY,
                query="q",
                limit=3,
            )


class TestForgettingAPerson:
    """The half the database cannot reach - and the half a partial wipe hides in."""

    async def test_it_deletes_exactly_that_persons_namespace(self):
        client = MagicMock()
        client.delete_users = AsyncMock()
        with patch.object(client_module, "_client", AsyncMock(return_value=client)):
            await client_module.mem0_forget_person(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                owner_key=PERSON_KEY,
            )

        assert client.delete_users.await_args.kwargs["user_ids"] == [f"{ORG}:{AGENT}:{PERSON_KEY}"]

    async def test_a_failure_is_raised_rather_than_reported_as_forgotten(self):
        """Somebody told their memory is gone stops asking, so a mem0 that refused
        must not be counted as a success."""
        client = MagicMock()
        client.delete_users = AsyncMock(side_effect=RuntimeError("token=sk-secret"))
        with (
            patch.object(client_module, "_client", AsyncMock(return_value=client)),
            pytest.raises(ExternalServiceError) as excinfo,
        ):
            await client_module.mem0_forget_person(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                owner_key=PERSON_KEY,
            )

        assert "sk-secret" not in str(excinfo.value.message)
        assert "sk-secret" not in str(excinfo.value.details)


class TestReadingMem0sAnswer:
    """mem0 has replied with more than one shape, and an unparsable answer is a
    search that found nothing rather than a failed run."""

    def test_an_envelope_is_read(self):
        assert [h.content for h in _hits({"results": [{"memory": "a"}]})] == ["a"]

    def test_a_bare_list_is_read(self):
        assert [h.content for h in _hits([{"text": "b"}])] == ["b"]

    def test_the_third_field_name_is_read(self):
        assert [h.content for h in _hits([{"content": "c"}])] == ["c"]

    def test_a_missing_score_is_zero_rather_than_a_crash(self):
        assert _hits([{"memory": "a"}])[0].score == 0.0

    def test_anything_else_is_no_hits(self):
        for answer in (None, "text", {"results": "nope"}, [1, 2], [{}]):
            assert _hits(answer) == []


class TestRemember:
    async def test_it_writes_to_the_runs_own_store(self):
        remember = AsyncMock()
        with patch("app.agents.capabilities.memory_mem0._toolset.mem0_remember", remember):
            out = await _toolset().remember(_ctx(_deps(person=PERSON)), "likes tea")
        assert out == "Remembered."
        assert remember.await_args.kwargs["owner_key"] == PERSON_KEY

    async def test_a_room_run_writes_the_room_and_never_the_speaker(self):
        """The leak the audience model exists to stop, on the semantic half: a
        private fact kept from a public channel is a fact the channel then
        recalls."""
        remember = AsyncMock()
        with patch("app.agents.capabilities.memory_mem0._toolset.mem0_remember", remember):
            await _toolset().remember(_ctx(_deps(person=PERSON, room=ROOM)), "we ship Fridays")
        assert remember.await_args.kwargs["owner_key"] == ROOM

    async def test_an_anonymous_run_is_refused_rather_than_written_anywhere(self):
        remember = AsyncMock()
        with patch("app.agents.capabilities.memory_mem0._toolset.mem0_remember", remember):
            out = await _toolset().remember(_ctx(_deps()), "something")
        assert out == _NO_STORE
        remember.assert_not_awaited()

    async def test_a_run_without_org_or_agent_is_refused(self):
        assert await _toolset().remember(_ctx(AgentDeps()), "x") == _NO_STORE

    async def test_the_personal_lever_off_leaves_a_private_run_nowhere(self):
        remember = AsyncMock()
        with patch("app.agents.capabilities.memory_mem0._toolset.mem0_remember", remember):
            out = await _toolset(allow_personal=False).remember(_ctx(_deps(person=PERSON)), "x")
        assert out == _NO_STORE
        remember.assert_not_awaited()


class TestRecall:
    async def test_it_searches_the_runs_own_store(self):
        recall = AsyncMock(return_value=[Mem0Fact("likes tea", 0.9)])
        with patch("app.agents.capabilities.memory_mem0._toolset.mem0_recall", recall):
            out = await _toolset().recall(_ctx(_deps(person=PERSON)), "drinks?")
        assert out == "- likes tea"
        assert recall.await_args.kwargs["owner_key"] == PERSON_KEY

    async def test_a_room_run_does_not_search_the_speakers_private_store(self):
        """The leak the audience model exists to stop, on the semantic half."""
        recall = AsyncMock(return_value=[])
        with patch("app.agents.capabilities.memory_mem0._toolset.mem0_recall", recall):
            await _toolset().recall(_ctx(_deps(person=PERSON, room=ROOM)), "q")
        assert recall.await_args.kwargs["owner_key"] == ROOM

    async def test_nothing_found_says_so(self):
        with patch(
            "app.agents.capabilities.memory_mem0._toolset.mem0_recall",
            AsyncMock(return_value=[]),
        ):
            assert (
                await _toolset().recall(_ctx(_deps(person=PERSON)), "q") == "No relevant memories."
            )

    async def test_the_limit_the_model_supplies_is_capped(self):
        recall = AsyncMock(return_value=[])
        with patch("app.agents.capabilities.memory_mem0._toolset.mem0_recall", recall):
            await _toolset().recall(_ctx(_deps(person=PERSON)), "q", limit=10_000)
        assert recall.await_args.kwargs["limit"] == 50

    async def test_a_nonsense_limit_is_floored_at_one(self):
        recall = AsyncMock(return_value=[])
        with patch("app.agents.capabilities.memory_mem0._toolset.mem0_recall", recall):
            await _toolset().recall(_ctx(_deps(person=PERSON)), "q", limit=0)
        assert recall.await_args.kwargs["limit"] == 1

    async def test_a_run_without_org_or_agent_is_refused(self):
        assert await _toolset().recall(_ctx(AgentDeps()), "q") == _NO_STORE


class TestConfig:
    def test_defaults_are_the_managed_cloud_with_personal_memory(self):
        config = MemoryMem0Config()
        assert config.base_url is None
        assert config.allow_personal is True

    def test_an_explicit_none_is_the_managed_cloud(self):
        """The validator runs on a value the Builder sent, and `null` is how the
        console says "cloud" - it must not be read as a malformed URL."""
        assert MemoryMem0Config(base_url=None).base_url is None

    def test_a_valid_self_hosted_url_is_accepted(self):
        assert MemoryMem0Config(base_url="https://mem0.internal").base_url

    def test_a_non_https_url_is_refused_at_publish(self):
        with pytest.raises(ValidationError):
            MemoryMem0Config(base_url="http://mem0.internal")

    def test_a_url_without_a_host_is_refused(self):
        with pytest.raises(ValidationError):
            MemoryMem0Config(base_url="https:///nope")

    def test_a_malformed_url_is_refused(self):
        with pytest.raises(ValidationError):
            MemoryMem0Config(base_url="https://[")


class TestBuilder:
    def test_it_reads_the_sealed_key(self):
        sid = uuid4()
        (capability,) = build(
            [CapabilityBinding(capability_id="memory_mem0", config={}, secret_id=sid)],
            secrets={sid: ApiKeySecret(api_key="k-9-12345")},
        )
        assert capability.api_key == "k-9-12345"

    def test_no_key_contributes_nothing(self):
        """A capability whose every call refuses is worse than one that is absent:
        the key is what makes it reachable at all."""
        ctx = CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="memory_mem0"), config=None
        )
        assert _build(ctx) is None

    def test_the_key_is_kept_out_of_the_repr(self):
        cap = MemoryMem0(api_key="k-secret")
        assert "k-secret" not in repr(cap)


class TestCapability:
    def test_the_toolset_is_built_once(self):
        cap = MemoryMem0(api_key="k")
        assert cap.get_toolset() is cap.get_toolset()

    def test_it_carries_the_two_tools_and_nothing_else(self):
        assert set(MemoryMem0(api_key="k").get_toolset().tools) == {"remember", "recall"}


class TestInstructions:
    def test_it_teaches_the_recall_habit(self):
        """A model holding `recall` but no standing instruction to use it answers
        "I have nothing saved" with the fact one search away."""
        assert "`recall`" in MemoryMem0(api_key="k").get_instructions()

    def test_it_does_not_promise_a_store_the_run_may_not_have(self):
        instructions = MemoryMem0(api_key="k").get_instructions()
        assert "personal" not in instructions
        assert "room" not in instructions
