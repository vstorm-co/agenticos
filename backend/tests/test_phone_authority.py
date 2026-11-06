"""Phone effects retain current person, source and live-session ownership."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.telephony import PhoneCall, PhoneContact
from app.schemas.telephony import PhoneContactConfig
from app.services.telephony import runtime
from app.services.telephony.policy import contact_fingerprint

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def contact_and_call() -> tuple[PhoneContact, PhoneCall, AuthContext]:
    user, org, identity, identifier = uuid4(), uuid4(), uuid4(), uuid4()
    contact = PhoneContact(
        id=identifier,
        organization_id=org,
        user_id=user,
        identity_generation=uuid4(),
        **PhoneContactConfig(identity_id=identity).model_dump(),
    )
    row = PhoneCall(
        id=uuid4(),
        organization_id=org,
        user_id=user,
        contact_id=identifier,
        contact_hash=contact_fingerprint(contact),
        destination="+15551234567",
        mode="report",
        purpose="direct",
        source_required=False,
        source_context_required=False,
    )
    return contact, row, AuthContext(organization_id=org, user_id=user, role="member")


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "contact_removed",
        "contact_replaced",
        "number_changed",
        "member_left",
        "agent_removed",
        "version_removed",
        "context_removed",
        "source_removed",
        "case_removed",
        "source_wrong_person",
        "source_agent_revoked",
        "routine_authorized",
    ],
)
async def test_outbound_authority_is_rechecked_at_every_live_boundary(
    monkeypatch, change: str
) -> None:
    contact, row, ctx = contact_and_call()
    monkeypatch.setattr(runtime.repo, "contact_by_id", AsyncMock(return_value=contact))
    monkeypatch.setattr(
        runtime.PhonePolicyService, "available_contact", AsyncMock(return_value=row.destination)
    )
    monkeypatch.setattr(runtime, "acting_member", AsyncMock(return_value=ctx))
    monkeypatch.setattr(runtime.AgentRegistryService, "get", AsyncMock())
    monkeypatch.setattr(runtime.ConversationService, "get_conversation", AsyncMock())
    if change == "contact_removed":
        monkeypatch.setattr(runtime.repo, "contact_by_id", AsyncMock(return_value=None))
    elif change == "contact_replaced":
        row.contact_hash = "old consent"
    elif change == "number_changed":
        row.destination = "+15550000000"
    elif change == "member_left":
        monkeypatch.setattr(runtime, "acting_member", AsyncMock(return_value=None))
    elif change == "agent_removed":
        row.mode = "conversation"
    elif change == "version_removed":
        row.mode, row.agent_id = "conversation", uuid4()
    elif change == "context_removed":
        row.source_context_required = True
    elif change == "source_removed":
        row.source_required = True
    elif change == "case_removed":
        row.purpose = "important"
    elif change in {"source_wrong_person", "source_agent_revoked", "routine_authorized"}:
        row.source_run_id = uuid4()
        monkeypatch.setattr(
            runtime.agent_run_repo,
            "get_run",
            AsyncMock(
                return_value=MagicMock(
                    user_id=uuid4() if change == "source_wrong_person" else ctx.user_id,
                    agent_id=uuid4(),
                )
            ),
        )
    if change == "routine_authorized":
        from app.services.routine_authority import RoutineAuthority

        source = runtime.agent_run_repo.get_run.return_value
        contact.agent_ids = [str(source.agent_id)]
        row.contact_hash = contact_fingerprint(contact)
        authority = MagicMock(check_in=AsyncMock())
        monkeypatch.setattr(RoutineAuthority, "capture", AsyncMock(return_value=authority))
        assert await runtime.live_contact(MagicMock(), row) == ctx
        assert authority.check_in.await_args.args[1] == source.agent_id
    elif change == "none":
        row.source_conversation_id = uuid4()
        assert await runtime.live_contact(MagicMock(), row) == ctx
    else:
        with pytest.raises(AuthorizationError):
            await runtime.live_contact(MagicMock(), row)


@pytest.mark.parametrize("change", ["none", "voice_removed", "wrong_run", "ended", "route_changed"])
async def test_only_the_current_voice_run_can_hang_up_its_call(monkeypatch, change: str) -> None:
    _, row, _ = contact_and_call()
    row.status, row.voice_call_id, row.endpoint_id = "active", uuid4(), uuid4()
    run_id = uuid4()
    monkeypatch.setattr(runtime.repo, "call", AsyncMock(return_value=row))
    monkeypatch.setattr(runtime.repo, "save", AsyncMock())
    voice = MagicMock(run_id=run_id)
    monkeypatch.setattr(runtime.voice_call_repo, "get", AsyncMock(return_value=voice))
    end = AsyncMock()
    monkeypatch.setattr(runtime, "end_media", end)
    if change == "voice_removed":
        monkeypatch.setattr(runtime.voice_call_repo, "get", AsyncMock(return_value=None))
    elif change == "wrong_run":
        voice.run_id = uuid4()
    elif change == "ended":
        row.status = "completed"
    endpoint_id = uuid4() if change == "route_changed" else row.endpoint_id
    db = MagicMock(commit=AsyncMock())
    if change == "none":
        await runtime.end_from_agent(db, row.id, source_run_id=run_id, endpoint_id=endpoint_id)
        assert row.status == "ending"
        end.assert_awaited_once()
    else:
        with pytest.raises(AuthorizationError):
            await runtime.end_from_agent(db, row.id, source_run_id=run_id, endpoint_id=endpoint_id)
        end.assert_not_awaited()
