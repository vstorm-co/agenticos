"""What the people who manage a WhatsApp line see of its customers: the view and its search (#2076)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.repositories.whatsapp_customer import CustomerRow
from app.schemas.channel_bot import WhatsAppCustomerList, WhatsAppCustomerRead
from app.services.channel_bot import ChannelBotService
from app.services.channels.whatsapp_erasure import CustomerErasure

pytestmark = pytest.mark.anyio

BOT = uuid.uuid4()
ORG = uuid.uuid4()
PHONE = "48600700800"


def _customer(*, phone: str | None = PHONE, linked: bool = False) -> CustomerRow:
    customer = MagicMock(
        id=uuid.uuid4(),
        bsuid="US.111",
        phone=phone,
        last_inbound_at=datetime(2026, 11, 4, tzinfo=UTC),
    )
    identity = MagicMock(
        user_id=uuid.uuid4() if linked else None,
        platform_display_name="Ana",
        platform_username="•••• 0800",
    )
    return CustomerRow(customer, identity)


async def _call(method: str, path: str, *, role: str, service, body: dict | None = None):
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role=role)
    app.dependency_overrides[deps.get_org_channel_bot_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            return await http.request(
                method,
                f"{settings.API_V1_STR}/channels/bots/{BOT}/whatsapp-customers{path}",
                json=body,
            )
    finally:
        app.dependency_overrides.clear()


def _listing() -> AsyncMock:
    service = MagicMock()
    read = WhatsAppCustomerRead(
        id=uuid.uuid4(),
        bsuid="US.111",
        phone=PHONE,
        profile_name="Ana",
        username=None,
        last_message_at=datetime(2026, 11, 4, tzinfo=UTC),
        linked=False,
    )
    service.whatsapp_customers = AsyncMock(return_value=WhatsAppCustomerList(items=[read], total=1))
    service.find_whatsapp_customers = AsyncMock(
        return_value=WhatsAppCustomerList(items=[read], total=1)
    )
    return service


@pytest.mark.security
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [("GET", "", None), ("POST", "/search", {"phone": "+48 600 700 800"})],
)
async def test_a_builder_may_not_see_the_customers(method, path, body):
    service = _listing()

    answer = await _call(method, path, role=OrgRoleName.BUILDER, service=service, body=body)

    assert answer.status_code == 403
    service.whatsapp_customers.assert_not_awaited()
    service.find_whatsapp_customers.assert_not_awaited()


@pytest.mark.security
async def test_an_owner_reads_full_numbers_in_the_listing_and_the_search():
    service = _listing()

    listed = await _call("GET", "?skip=0&limit=20", role=OrgRoleName.OWNER, service=service)
    found = await _call(
        "POST",
        "/search",
        role=OrgRoleName.OWNER,
        service=service,
        body={"phone": "+48 600 700 800"},
    )

    assert listed.status_code == found.status_code == 200
    assert listed.json()["items"][0]["phone"] == PHONE
    assert found.json()["items"][0]["phone"] == PHONE
    assert service.find_whatsapp_customers.await_args.args == (BOT, "+48 600 700 800")


@pytest.mark.security
async def test_the_search_takes_no_query_parameter_for_the_number():
    schema = app.openapi()["paths"][
        f"{settings.API_V1_STR}/channels/bots/{{bot_id}}/whatsapp-customers/search"
    ]["post"]

    assert [p["name"] for p in schema.get("parameters", []) if p["in"] == "query"] == []
    assert "requestBody" in schema


@pytest.mark.security
async def test_a_malformed_number_is_refused_before_the_service():
    service = _listing()

    answer = await _call(
        "POST", "/search", role=OrgRoleName.OWNER, service=service, body={"phone": "abc"}
    )

    assert answer.status_code == 422
    service.find_whatsapp_customers.assert_not_awaited()


@pytest.mark.security
async def test_another_organizations_bot_is_not_found():
    service = ChannelBotService(MagicMock(), organization_id=ORG)
    with patch(
        "app.services.channel_bot.channel_bot_repo.get_for_org", AsyncMock(return_value=None)
    ) as lookup:
        with pytest.raises(NotFoundError):
            await service.whatsapp_customers(BOT, skip=0, limit=10)
        with pytest.raises(NotFoundError):
            await service.find_whatsapp_customers(BOT, "+48 600 700 800")

    assert lookup.await_args.kwargs["organization_id"] == ORG


@pytest.mark.security
async def test_a_bot_of_another_platform_is_refused():
    service = ChannelBotService(MagicMock(), organization_id=ORG)
    bot = MagicMock(platform="telegram")
    with patch(
        "app.services.channel_bot.channel_bot_repo.get_for_org", AsyncMock(return_value=bot)
    ):
        for call in (
            service.whatsapp_customers(BOT, skip=0, limit=10),
            service.find_whatsapp_customers(BOT, "+48 600 700 800"),
        ):
            with pytest.raises(BadRequestError):
                await call


@pytest.fixture(autouse=True)
def _members_are_active():
    async def everyone(db, *, organization_id, user_ids):
        return {user_id: uuid.uuid4() for user_id in user_ids}

    with patch(
        "app.services.channel_bot.member_repo.get_active_ids", AsyncMock(side_effect=everyone)
    ) as active:
        yield active


@pytest.mark.security
async def test_a_linked_row_shows_no_number_and_a_departed_member_is_unlinked(_members_are_active):
    service = ChannelBotService(MagicMock(), organization_id=ORG)
    rows = [_customer(linked=True), _customer(linked=True)]
    first = rows[0].identity.user_id
    _members_are_active.side_effect = None
    _members_are_active.return_value = {first: uuid.uuid4()}
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            AsyncMock(return_value=MagicMock(platform="whatsapp", id=BOT)),
        ),
        patch(
            "app.services.channel_bot.whatsapp_customer_repo.list_for_bot",
            AsyncMock(return_value=(rows, 2)),
        ),
    ):
        listed = await service.whatsapp_customers(BOT, skip=0, limit=10)

    assert [(c.linked, c.phone) for c in listed.items] == [(True, None), (False, PHONE)]


@pytest.mark.security
async def test_the_service_returns_rows_with_their_standing_and_searches_digits_only():
    service = ChannelBotService(MagicMock(), organization_id=ORG)
    bot = MagicMock(platform="whatsapp", id=BOT)
    rows = [_customer(), _customer(phone=None, linked=True)]
    with (
        patch("app.services.channel_bot.channel_bot_repo.get_for_org", AsyncMock(return_value=bot)),
        patch(
            "app.services.channel_bot.whatsapp_customer_repo.list_for_bot",
            AsyncMock(return_value=(rows, 2)),
        ),
        patch(
            "app.services.channel_bot.whatsapp_customer_repo.find_by_phone",
            AsyncMock(return_value=rows[:1]),
        ) as find,
    ):
        listed = await service.whatsapp_customers(BOT, skip=0, limit=10)
        found = await service.find_whatsapp_customers(BOT, "+48 (600) 700-800")
        nothing = await service.find_whatsapp_customers(BOT, "+" + "1" * 16)

    assert listed.total == 2
    assert [(c.phone, c.linked, c.profile_name) for c in listed.items] == [
        (PHONE, False, "Ana"),
        (None, True, "Ana"),
    ]
    assert find.await_args.kwargs == {"organization_id": ORG, "bot_id": BOT, "phone": PHONE}
    assert [c.phone for c in found.items] == [PHONE]
    assert nothing.items == [] and nothing.total == 0


async def test_a_customer_with_no_chat_account_row_is_unlinked_and_unnamed():
    service = ChannelBotService(MagicMock(), organization_id=ORG)
    row = CustomerRow(_customer().customer, None)
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            AsyncMock(return_value=MagicMock(platform="whatsapp")),
        ),
        patch(
            "app.services.channel_bot.whatsapp_customer_repo.list_for_bot",
            AsyncMock(return_value=([row], 1)),
        ),
    ):
        listed = await service.whatsapp_customers(BOT, skip=0, limit=10)

    assert (listed.items[0].linked, listed.items[0].profile_name, listed.items[0].username) == (
        False,
        None,
        None,
    )


def _forget_service(result=None, error: Exception | None = None) -> MagicMock:
    service = MagicMock()
    service.forget_whatsapp_customer = AsyncMock(return_value=result, side_effect=error)
    return service


@pytest.mark.security
async def test_a_builder_may_not_erase_a_customer():
    service = _forget_service(CustomerErasure())

    answer = await _call(
        "POST", "/forget", role=OrgRoleName.BUILDER, service=service,
        body={"customer_id": str(uuid.uuid4())},
    )  # fmt: skip

    assert answer.status_code == 403
    service.forget_whatsapp_customer.assert_not_awaited()


@pytest.mark.security
async def test_an_owner_erasing_a_customer_gets_the_counts_and_is_named_as_the_actor():
    service = _forget_service(
        CustomerErasure(identities=1, conversations=2, handback_jobs_running=1)
    )
    customer_id = uuid.uuid4()

    answer = await _call(
        "POST", "/forget", role=OrgRoleName.OWNER, service=service,
        body={"customer_id": str(customer_id)},
    )  # fmt: skip

    assert answer.status_code == 200
    assert answer.json()["conversations"] == 2
    assert answer.json()["handback_jobs_running"] == 1
    call = service.forget_whatsapp_customer.await_args
    assert call.args == (BOT, customer_id)
    assert set(call.kwargs) == {"actor_user_id"} and call.kwargs["actor_user_id"] is not None


@pytest.mark.security
async def test_a_linked_customer_is_a_conflict_on_the_route():
    service = _forget_service(error=ConflictError(message="linked"))

    answer = await _call(
        "POST", "/forget", role=OrgRoleName.OWNER, service=service,
        body={"customer_id": str(uuid.uuid4())},
    )  # fmt: skip

    assert answer.status_code == 409


@pytest.mark.security
async def test_another_organizations_bot_and_another_bots_customer_are_not_found():
    service = ChannelBotService(MagicMock(), organization_id=ORG)
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org", AsyncMock(return_value=None)
        ),
        pytest.raises(NotFoundError),
    ):
        await service.forget_whatsapp_customer(BOT, uuid.uuid4(), actor_user_id=None)
    bot = MagicMock(platform="whatsapp", id=BOT)
    with (
        patch("app.services.channel_bot.channel_bot_repo.get_for_org", AsyncMock(return_value=bot)),
        patch(
            "app.services.channel_bot.whatsapp_customer_repo.get_in_bot",
            AsyncMock(return_value=None),
        ) as lookup,
        patch("app.services.channel_bot.WhatsAppErasureService") as erasure,
        pytest.raises(NotFoundError),
    ):
        await service.forget_whatsapp_customer(BOT, uuid.uuid4(), actor_user_id=None)

    assert lookup.await_args.kwargs["bot_id"] == BOT
    assert lookup.await_args.kwargs["organization_id"] == ORG
    erasure.assert_not_called()


@pytest.mark.security
async def test_the_service_erases_the_customer_found_in_the_bot_as_the_console():
    service = ChannelBotService(MagicMock(), organization_id=ORG)
    bot = MagicMock(platform="whatsapp", id=BOT)
    customer = MagicMock(bsuid="US.111")
    actor = uuid.uuid4()
    with (
        patch("app.services.channel_bot.channel_bot_repo.get_for_org", AsyncMock(return_value=bot)),
        patch(
            "app.services.channel_bot.whatsapp_customer_repo.get_in_bot",
            AsyncMock(return_value=customer),
        ),
        patch("app.services.channel_bot.WhatsAppErasureService") as erasure,
    ):
        erasure.return_value.forget = AsyncMock(return_value=CustomerErasure(identities=1))
        result = await service.forget_whatsapp_customer(BOT, uuid.uuid4(), actor_user_id=actor)

    assert result.identities == 1
    assert erasure.return_value.forget.await_args.kwargs == {
        "bsuid": "US.111", "named_by": "bsuid", "actor_user_id": actor, "via": "console",
    }  # fmt: skip


@pytest.mark.security
async def test_forgetting_on_a_bot_of_another_platform_is_a_400():
    service = ChannelBotService(MagicMock(), organization_id=ORG)
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            AsyncMock(return_value=MagicMock(platform="telegram")),
        ),
        pytest.raises(BadRequestError),
    ):
        await service.forget_whatsapp_customer(BOT, uuid.uuid4(), actor_user_id=None)
