"""`invite-members`: several invitations at once, and their links on stdout.

The command exists because a deployment with no `SMTP_*` emails nobody, and an
invitation token is returned once and stored nowhere a second read can reach - so
the links have to be printed to be passed on at all. These tests are mostly about
what it prints, since that output *is* the feature.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from click.testing import CliRunner

from app.commands import invite_members as cmd
from app.core.exceptions import AlreadyExistsError

ORG_ID = uuid4()
OWNER_ID = uuid4()


@pytest.fixture(autouse=True)
def _session(monkeypatch):
    @asynccontextmanager
    async def session() -> AsyncGenerator[object, None]:
        yield object()

    monkeypatch.setattr(cmd, "get_db_context", session)
    monkeypatch.setattr(cmd.settings, "FRONTEND_URL", "https://agenticos.example/")


def _org(monkeypatch, *, found: bool = True) -> None:
    monkeypatch.setattr(
        cmd.organization_repo,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(name="Acme") if found else None),
    )


def _owner(monkeypatch, owner_id=OWNER_ID) -> None:
    monkeypatch.setattr(cmd.member_repo, "first_owner_id", AsyncMock(return_value=owner_id))


def _invites(monkeypatch, outcomes: list[object]) -> None:
    """`InvitationService.invite` answering each address in turn.

    An entry is either `(email, token, delivered)` or an exception to raise.
    """
    calls = iter(outcomes)

    async def invite(organization_id, email, role, requester_id):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        address, token, delivered = outcome
        return SimpleNamespace(email=address, token=token), delivered

    monkeypatch.setattr(cmd, "InvitationService", lambda db: SimpleNamespace(invite=invite))


def _run(*args: str):
    return CliRunner().invoke(cmd.invite_members, list(args))


def test_it_prints_each_address_beside_its_link(monkeypatch) -> None:
    _org(monkeypatch)
    _owner(monkeypatch)
    _invites(monkeypatch, [("a@x.test", "tok-a", True), ("b@x.test", "tok-b", True)])

    result = _run(str(ORG_ID), "a@x.test", "b@x.test")

    assert result.exit_code == 0, result.output
    assert "a@x.test  https://agenticos.example/invitations/tok-a" in result.output
    assert "b@x.test  https://agenticos.example/invitations/tok-b" in result.output
    assert "2 invitation(s) created." in result.output


def test_it_says_when_nothing_was_emailed(monkeypatch) -> None:
    # The whole reason for printing links. A deployment with no mail service
    # accepted nothing, and the operator has to pass these on by hand.
    _org(monkeypatch)
    _owner(monkeypatch)
    _invites(monkeypatch, [("a@x.test", "tok-a", False)])

    result = _run(str(ORG_ID), "a@x.test")

    assert "No email left this deployment" in result.output


def test_it_says_when_only_some_were_emailed(monkeypatch) -> None:
    _org(monkeypatch)
    _owner(monkeypatch)
    _invites(monkeypatch, [("a@x.test", "tok-a", True), ("b@x.test", "tok-b", False)])

    result = _run(str(ORG_ID), "a@x.test", "b@x.test")

    assert "some were not" in result.output


def test_one_refused_address_does_not_cost_the_others(monkeypatch) -> None:
    # Every refusal in `invite` precedes the row it would have written, so the
    # session is clean and the batch continues. A member who already has a
    # pending invitation must not take the other nineteen down with them.
    _org(monkeypatch)
    _owner(monkeypatch)
    _invites(
        monkeypatch,
        [
            AlreadyExistsError(message="A pending invitation already exists for this email"),
            ("b@x.test", "tok-b", True),
        ],
    )

    result = _run(str(ORG_ID), "a@x.test", "b@x.test")

    assert result.exit_code == 0, result.output
    assert "a@x.test: A pending invitation already exists" in result.output
    assert "tok-b" in result.output
    assert "1 invitation(s) created." in result.output
    assert "1 refused" in result.output


def test_every_address_refused_creates_nothing_and_says_so(monkeypatch) -> None:
    _org(monkeypatch)
    _owner(monkeypatch)
    _invites(monkeypatch, [AlreadyExistsError(message="Already a member")])

    result = _run(str(ORG_ID), "a@x.test")

    assert "Nothing created." in result.output


def test_a_malformed_organization_id_is_refused_before_any_query(monkeypatch) -> None:
    get_by_id = AsyncMock()
    monkeypatch.setattr(cmd.organization_repo, "get_by_id", get_by_id)

    result = _run("not-a-uuid", "a@x.test")

    assert "Not a UUID" in result.output
    get_by_id.assert_not_called()


def test_an_unknown_organization_is_named_rather_than_crashed_into(monkeypatch) -> None:
    _org(monkeypatch, found=False)

    result = _run(str(ORG_ID), "a@x.test")

    assert f"No organization with id {ORG_ID}" in result.output


def test_an_organization_with_no_owner_asks_who_to_invite_as(monkeypatch) -> None:
    # A role gate has to have a role to weigh the offered one against, so there
    # is nothing to fall back to here.
    _org(monkeypatch)
    _owner(monkeypatch, owner_id=None)

    result = _run(str(ORG_ID), "a@x.test")

    assert "no owner to invite as" in result.output


def test_acting_as_somebody_who_has_no_account(monkeypatch) -> None:
    _org(monkeypatch)
    monkeypatch.setattr(cmd.user_repo, "get_by_email", AsyncMock(return_value=None))

    result = _run(str(ORG_ID), "a@x.test", "--as", "ghost@x.test")

    assert "No user with email ghost@x.test" in result.output


def test_acting_as_somebody_outside_the_organization(monkeypatch) -> None:
    _org(monkeypatch)
    monkeypatch.setattr(
        cmd.user_repo, "get_by_email", AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    )
    monkeypatch.setattr(cmd.member_repo, "get", AsyncMock(return_value=None))

    result = _run(str(ORG_ID), "a@x.test", "--as", "outsider@x.test")

    assert "not a member of this organization" in result.output


def test_acting_as_a_named_member_invites_under_their_authority(monkeypatch) -> None:
    acting_id = uuid4()
    _org(monkeypatch)
    monkeypatch.setattr(
        cmd.user_repo, "get_by_email", AsyncMock(return_value=SimpleNamespace(id=acting_id))
    )
    monkeypatch.setattr(
        cmd.member_repo, "get", AsyncMock(return_value=SimpleNamespace(role="admin"))
    )
    seen: list[tuple[str, UUID]] = []

    async def invite(organization_id, email, role, requester_id):
        seen.append((role, requester_id))
        return SimpleNamespace(email=email, token="tok"), True

    monkeypatch.setattr(cmd, "InvitationService", lambda db: SimpleNamespace(invite=invite))

    result = _run(str(ORG_ID), "a@x.test", "--role", "viewer", "--as", "admin@x.test")

    assert result.exit_code == 0, result.output
    assert seen == [("viewer", acting_id)]
