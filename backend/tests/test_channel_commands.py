"""Which organization a `channel-*` command acts for.

Every one of the five built `ChannelBotService(db)` with no organization, and
every call they make is a management call - so the first property that read the
tenant raised `RuntimeError`. Two commands showed the traceback; the other three
caught it in a bare `except Exception` and printed **"Bot not found"** about a
bot that existed, which is a confident wrong answer rather than a failure
(#1350). None of the five worked, and `docs/channels.md` names them as the only
route on a deployment with no browser pointed at it.

They had no tests at all. That is the whole reason it shipped, so these cover the
decision rather than the plumbing: which tenant a command acts for, and what it
says when it cannot tell.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.commands.channel import _resolve_org
from app.repositories import organization_repo

pytestmark = pytest.mark.anyio


def _org(name: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), name=name)


class TestWhichOrganizationACommandActsFor:
    async def test_an_explicit_org_is_used_without_asking_the_database(self, monkeypatch):
        """No lookup at all: an operator who named the tenant has answered the
        question, and a deployment with a hundred organizations should not pay a
        query to be told so."""
        listed = AsyncMock()
        monkeypatch.setattr(organization_repo, "list_all", listed)
        wanted = uuid4()

        assert await _resolve_org(None, str(wanted)) == wanted
        listed.assert_not_awaited()

    async def test_the_only_organization_needs_no_flag(self, monkeypatch):
        """A self-hosted install with one tenant should not name it five times a
        session."""
        only = _org("Acme")
        monkeypatch.setattr(organization_repo, "list_all", AsyncMock(return_value=[only]))

        assert await _resolve_org(None, None) == only.id

    async def test_several_organizations_are_asked_about_rather_than_guessed(
        self, monkeypatch, capsys
    ):
        """Picking one would act on somebody else's bots, so it refuses - and
        names them, because the id is what the flag wants and nobody has it
        memorised."""
        first, second = _org("Acme"), _org("Globex")
        monkeypatch.setattr(organization_repo, "list_all", AsyncMock(return_value=[first, second]))

        with pytest.raises(SystemExit):
            await _resolve_org(None, None)

        printed = capsys.readouterr().out
        assert "--org" in printed
        assert str(first.id) in printed and str(second.id) in printed

    async def test_no_organizations_says_what_to_run(self, monkeypatch, capsys):
        """A fresh deployment, where the answer is bootstrap rather than a flag."""
        monkeypatch.setattr(organization_repo, "list_all", AsyncMock(return_value=[]))

        with pytest.raises(SystemExit):
            await _resolve_org(None, None)

        assert "platform-bootstrap" in capsys.readouterr().out

    async def test_something_that_is_not_an_id_is_refused_before_any_query(
        self, monkeypatch, capsys
    ):
        listed = AsyncMock()
        monkeypatch.setattr(organization_repo, "list_all", listed)

        with pytest.raises(SystemExit):
            await _resolve_org(None, "the-acme-one")

        assert "Not an organization id" in capsys.readouterr().out
        listed.assert_not_awaited()

    async def test_the_resolved_id_is_a_uuid_the_service_can_scope_on(self, monkeypatch):
        """The type matters: `organization_id` reaches a repository as a bind
        parameter, and a string there is a comparison that never matches."""
        only = _org("Acme")
        monkeypatch.setattr(organization_repo, "list_all", AsyncMock(return_value=[only]))

        assert isinstance(await _resolve_org(None, None), UUID)
        assert isinstance(await _resolve_org(None, str(only.id)), UUID)


class TestThePublicLineCommand:
    """`channel-public-line` prints the warning, and its switch refuses as the API does."""

    @staticmethod
    def _read(**changes):
        from app.schemas.channel_bot import PublicLineRead

        values = {
            "answers_unlinked": False,
            "agent_name": "Front desk",
            "agent_version": 3,
            "agent_monthly_usd": None,
            "organization_monthly_usd": None,
            "can_turn_on": False,
            "accept_customer_files": False,
            "voice": "off",
            "rate_limit_rpm": 10,
            "approval_expiry_hours": 72,
            "recording_max_mb": 2,
            "file_max_mb": 5,
            "reaches": [{"kind": "knowledge", "names": ["Handbook"], "detail": None}],
            "refused": ["memory"],
        }
        return PublicLineRead(**{**values, **changes})

    @staticmethod
    def _service(read, bot=None, update=None):
        from contextlib import asynccontextmanager

        svc = AsyncMock()
        svc.public_line.return_value = read
        svc.get.return_value = bot or SimpleNamespace(
            access_policy={"mode": "open", "rate_limit_rpm": 10}
        )
        if update is not None:
            svc.update.side_effect = update

        @asynccontextmanager
        async def opened(_org):
            yield svc

        return svc, opened

    def _run(self, monkeypatch, svc_opened, *args):
        from click.testing import CliRunner

        from app.commands import channel

        monkeypatch.setattr(channel, "_channel_service", svc_opened)
        return CliRunner().invoke(channel.channel_public_line, [*args])

    def test_it_prints_every_line_of_the_warning(self, monkeypatch):
        _svc, opened = self._service(self._read())

        result = self._run(monkeypatch, opened, "--bot-id", str(uuid4()))

        assert result.exit_code == 0
        for expected in ("Front desk", "Handbook", "72", "No spending limit", "memory"):
            assert expected in result.output

    def test_it_says_in_words_why_voice_notes_are_refused(self, monkeypatch):
        _svc, opened = self._service(self._read(voice="refused_no_org_cap"))

        result = self._run(monkeypatch, opened, "--bot-id", str(uuid4()))

        assert "refused_no_org_cap" not in result.output
        assert "monthly spending cap" in result.output

    def test_on_goes_through_the_service_and_its_refusal_is_printed(self, monkeypatch):
        from app.core.exceptions import BadRequestError

        def refuse(*_a, **_k):
            raise BadRequestError(message="needs a spending limit")

        svc, opened = self._service(self._read(), update=refuse)

        result = self._run(monkeypatch, opened, "--bot-id", str(uuid4()), "--on")

        assert result.exit_code != 0
        assert "needs a spending limit" in result.output
        sent = svc.update.await_args.args[1].access_policy
        assert sent.answer_unlinked_direct is True
        assert sent.rate_limit_rpm == 10

    def test_off_closes_the_line(self, monkeypatch):
        svc, opened = self._service(self._read(answers_unlinked=True, can_turn_on=True))

        result = self._run(monkeypatch, opened, "--bot-id", str(uuid4()), "--off")

        assert result.exit_code == 0
        assert svc.update.await_args.args[1].access_policy.answer_unlinked_direct is False

    def test_a_bot_id_that_is_no_bot_is_said_so(self, monkeypatch):
        from app.core.exceptions import NotFoundError

        svc, opened = self._service(self._read())
        svc.public_line.side_effect = NotFoundError(message="Channel bot not found")

        result = self._run(monkeypatch, opened, "--bot-id", str(uuid4()))

        assert result.exit_code != 0
        assert "not found" in result.output.lower()
