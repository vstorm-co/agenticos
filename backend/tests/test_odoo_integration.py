"""Odoo keys stay on approved origins and expose only fixed business operations."""

from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.exceptions import AuthorizationError, BadRequestError, ExternalServiceError
from app.core.odoo_credential import OdooCredential
from app.services.integrations import Operation, odoo, odoo_feed
from app.services.integrations.catalog import PRODUCTS

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def credential():
    return OdooCredential(
        origin="https://erp.example.com", database="company", api_key=SecretStr("private-key")
    )


def operation(name):
    return next(op for op in PRODUCTS["odoo_contacts"].operations if op.id == name)


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(odoo.settings, "ODOO_ALLOWED_HOSTS", ["erp.example.com"])

    def install(handler):
        monkeypatch.setattr(
            odoo.httpx,
            "AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


@pytest.mark.parametrize(
    "origin",
    [
        "http://erp.example.com",
        "https://user:password@erp.example.com",
        "https://erp.example.com/path",
        "https://erp.example.com?key=x",
        "https://erp.example.com#x",
        "https://erp.example.com:8443",
        "https://",
        "https://erp.example.com\n",
    ],
)
async def test_only_a_plain_tls_origin_can_be_saved(origin):
    with pytest.raises(ValidationError):
        OdooCredential(origin=origin, database="company", api_key="key")


async def test_credentials_validate_headers_and_normalize_origin():
    assert (
        OdooCredential(origin="https://erp.example.com/", database="company", api_key="key").origin
        == "https://erp.example.com"
    )
    for field in ("database", "api_key"):
        values = {
            "origin": "https://erp.example.com",
            "database": "company",
            "api_key": "key",
            field: "bad\nvalue",
        }
        with pytest.raises(ValidationError):
            OdooCredential.model_validate(values)


async def test_connect_checks_the_key_at_the_exact_origin_without_redirects(transport):
    def respond(request):
        assert str(request.url) == "https://erp.example.com/json/2/res.users/context_get"
        assert request.headers["Authorization"] == "bearer private-key"
        assert request.headers["X-Odoo-Database"] == "company"
        return httpx.Response(200, json={"uid": 7})

    transport(respond)
    await odoo.identify(credential())


@pytest.mark.parametrize(
    "name,body,expected",
    [
        (
            "search_contacts",
            {},
            {
                "domain": [],
                "fields": ["id", "display_name"],
                "limit": 50,
                "offset": 0,
                "order": "id asc",
            },
        ),
        ("read_contacts", {"ids": [7]}, {"ids": [7], "fields": ["id", "display_name"]}),
        (
            "fields_contacts",
            None,
            {"attributes": ["string", "type", "required", "readonly", "relation"]},
        ),
        ("create_contacts", {"values": {"name": "Acme"}}, {"vals_list": [{"name": "Acme"}]}),
        (
            "update_contacts",
            {"ids": [7], "values": {"name": "Acme"}},
            {"ids": [7], "vals": {"name": "Acme"}},
        ),
    ],
)
async def test_native_operations_preserve_the_json2_contract(transport, name, body, expected):
    import json

    def respond(request):
        assert json.loads(request.content) == expected
        assert request.url.path.startswith("/json/2/res.partner/")
        return httpx.Response(200, json=[{"id": 7}])

    transport(respond)
    assert await odoo.execute(
        credential(), operation(name), parameters={}, query={}, body=body
    ) == {"result": [{"id": 7}]}


@pytest.mark.parametrize(
    "name,body",
    [
        ("fields_contacts", {"context": {"sudo": True}}),
        ("read_contacts", {"ids": [0]}),
        ("read_contacts", {"ids": [True]}),
        ("read_contacts", {"ids": [1], "fields": ["bad field"]}),
        ("search_contacts", {"limit": 101}),
        ("search_contacts", {"order": "id;drop table"}),
        ("create_contacts", {"values": {"id": 4}}),
        ("create_contacts", {"values": {"user.name": "x"}}),
        ("create_contacts", {"values": {"bad key": "x"}}),
        ("create_contacts", {"context": {"sudo": True}}),
    ],
)
async def test_unbounded_or_privileged_native_arguments_are_refused(name, body):
    with pytest.raises(BadRequestError):
        await odoo.execute(credential(), operation(name), parameters={}, query={}, body=body)


@pytest.mark.parametrize("parameters,query", [({"model": "res.users"}, {}), ({}, {"sudo": "true"})])
async def test_model_and_method_cannot_be_overridden(parameters, query):
    with pytest.raises(BadRequestError):
        await odoo.execute(
            credential(), operation("search_contacts"), parameters=parameters, query=query, body={}
        )
    with pytest.raises(BadRequestError):
        await odoo.execute(
            credential(),
            Operation("admin", "No", "POST", "odoo://res.users/write", ()),
            parameters={},
            query={},
            body={},
        )


async def test_removed_host_authorization_stops_existing_keys(monkeypatch):
    monkeypatch.setattr(odoo.settings, "ODOO_ALLOWED_HOSTS", [])
    with pytest.raises(AuthorizationError):
        await odoo.identify(credential())


@pytest.mark.parametrize(
    "status,content",
    [(401, b"private-key"), (302, b"private-key"), (200, b"not json"), (200, b"x" * 2_000_001)],
)
async def test_provider_failure_does_not_echo_credentials_or_follow_redirects(
    transport, status, content
):
    transport(
        lambda request: httpx.Response(
            status, content=content, headers={"Location": "https://evil.example.com"}
        )
    )
    with pytest.raises(ExternalServiceError) as caught:
        await odoo.identify(credential())
    assert "private-key" not in str(caught.value)


async def test_transport_uncertainty_never_replays_a_write(transport):
    calls = 0

    def refuse(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("private-key")

    transport(refuse)
    with pytest.raises(ExternalServiceError, match="already have completed"):
        await odoo.execute(
            credential(),
            operation("create_contacts"),
            parameters={},
            query={},
            body={"values": {"name": "Acme"}},
        )
    assert calls == 1


async def test_large_requests_are_refused_before_sending_a_key(transport):
    transport(lambda request: pytest.fail("must not send"))
    with pytest.raises(BadRequestError, match="too large"):
        await odoo.execute(
            credential(),
            operation("create_contacts"),
            parameters={},
            query={},
            body={"values": {"name": "x" * 1_000_001}},
        )


@pytest.mark.parametrize("result", [[], {}, {"uid": "7"}])
async def test_connection_requires_an_authenticated_user_context(transport, result):
    transport(lambda request: httpx.Response(200, json=result))
    with pytest.raises(ExternalServiceError, match="authenticated"):
        await odoo.identify(credential())


async def test_feed_baselines_quietly_and_pages_records_by_timestamp_and_id(monkeypatch):
    read = AsyncMock(
        side_effect=[
            {"result": [{"id": 7, "write_date": "2026-11-07 10:00:00", "display_name": "Acme"}]},
            {"result": [{"id": 8, "write_date": "2026-11-07 10:00:00", "display_name": "Beta"}]},
            {"result": []},
        ]
    )
    monkeypatch.setattr(odoo_feed, "execute", read)
    baseline = await odoo_feed.changes(credential(), "odoo_contacts", None)
    assert baseline.events == []
    changed = await odoo_feed.changes(credential(), "odoo_contacts", baseline.cursor)
    assert changed.events[0].payload["record"]["id"] == 8
    body = read.await_args_list[1].kwargs["body"]
    assert body["limit"] == 100
    assert body["domain"][-1] == ["id", ">", 7]
    quiet = await odoo_feed.changes(credential(), "odoo_contacts", changed.cursor)
    assert quiet.events == [] and quiet.cursor == changed.cursor


async def test_empty_odoo_baseline_still_sees_the_first_future_record(monkeypatch):
    read = AsyncMock(return_value={"result": []})
    monkeypatch.setattr(odoo_feed, "execute", read)
    initial = await odoo_feed.changes(credential(), "odoo_contacts", None)
    assert initial.cursor["models"]["res.partner"]["id"] == 0


@pytest.mark.parametrize(
    "cursor",
    [
        {"product_id": "odoo_crm"},
        {"product_id": "odoo_contacts", "models": []},
        {"product_id": "odoo_contacts", "models": {"res.partner": {"id": -1, "stamp": "bad"}}},
    ],
)
async def test_feed_cursors_cannot_change_models_or_skip_validation(cursor):
    with pytest.raises(BadRequestError):
        await odoo_feed.changes(credential(), "odoo_contacts", cursor)
    with pytest.raises(BadRequestError):
        await odoo_feed.changes(credential(), "gmail", None)


@pytest.mark.parametrize(
    "rows",
    [
        {},
        [False],
        [{"id": 1, "write_date": "2026-20-99 00:00:00"}],
        [{"id": 7, "write_date": "2026-11-07 10:00:00"}],
    ],
)
async def test_invalid_or_repeated_feed_rows_never_advance_a_cursor(monkeypatch, rows):
    monkeypatch.setattr(odoo_feed, "execute", AsyncMock(return_value={"result": rows}))
    cursor = {
        "product_id": "odoo_contacts",
        "models": {"res.partner": {"id": 7, "stamp": "2026-11-07 10:00:00"}},
    }
    with pytest.raises(ExternalServiceError):
        await odoo_feed.changes(credential(), "odoo_contacts", cursor)


@pytest.mark.parametrize(
    "product,operation_id,method",
    [
        ("odoo_sales", "confirm_orders", "action_confirm"),
        ("odoo_accounting", "post_invoices", "action_post"),
        ("odoo_inventory", "confirm_transfers", "action_confirm"),
        ("odoo_inventory", "reserve_transfers", "action_assign"),
        ("odoo_inventory", "validate_transfers", "button_validate"),
    ],
)
async def test_business_actions_use_odoo_validation_and_preserve_required_wizards(
    transport, product, operation_id, method
):
    import json

    selected = next(op for op in PRODUCTS[product].operations if op.id == operation_id)
    wizard = {"type": "ir.actions.act_window", "res_model": "stock.backorder.confirmation"}

    def respond(request):
        assert request.url.path.endswith("/" + method)
        assert json.loads(request.content) == {"ids": [7]}
        return httpx.Response(200, json=wizard)

    transport(respond)
    assert selected.side_effecting
    result = await odoo.execute(credential(), selected, parameters={}, query={}, body={"ids": [7]})
    assert result == {"result": wizard}


async def test_direct_state_writes_cannot_skip_odoo_business_validation():
    selected = next(
        op for op in PRODUCTS["odoo_inventory"].operations if op.id == "update_transfers"
    )
    with pytest.raises(BadRequestError, match="business action"):
        await odoo.execute(
            credential(),
            selected,
            parameters={},
            query={},
            body={"ids": [7], "values": {"state": "done"}},
        )


@pytest.mark.parametrize(
    "value",
    [
        {"login": "new-user"},
        [[0, 0, {"login": "new-user"}]],
        [[1, 7, {"groups_id": [[6, 0, [1]]]}]],
        [[2, 7, 0]],
        [[4, 0]],
        [[4, 1, 9]],
        [[6, 0, [True]]],
        [[6, 1, [7]]],
        [[6, 0, "7"]],
        [[6, 0, list(range(1, 102))]],
        [[5, 1, 0]],
        [["4", 7]],
        [False],
        [[4, 7]] * 101,
    ],
)
async def test_relational_values_cannot_escape_to_unlisted_model_writes(value):
    with pytest.raises(BadRequestError, match="related records"):
        await odoo.execute(
            credential(),
            operation("update_contacts"),
            parameters={},
            query={},
            body={"ids": [7], "values": {"user_ids": value}},
        )


@pytest.mark.parametrize("value", [[], [[4, 7]], [[4, 7, 0]], [[6, 0, [7, 8]]], [[5]], [[5, 0, 0]]])
async def test_existing_relation_ids_can_be_linked_without_nested_model_mutations(transport, value):
    transport(lambda request: httpx.Response(200, json=True))
    result = await odoo.execute(
        credential(),
        operation("update_contacts"),
        parameters={},
        query={},
        body={"ids": [7], "values": {"category_id": value}},
    )
    assert result == {"result": True}


@pytest.mark.parametrize("kind", [None, "entry", [], "out_invoice"])
async def test_creating_an_invoice_requires_its_accounting_kind(transport, kind):
    selected = next(
        op for op in PRODUCTS["odoo_accounting"].operations if op.id == "create_invoices"
    )
    transport(lambda request: httpx.Response(200, json=[7]))
    body = {"values": {"move_type": kind}}
    if kind != "out_invoice":
        with pytest.raises(BadRequestError, match="move_type"):
            await odoo.execute(credential(), selected, parameters={}, query={}, body=body)
    else:
        assert await odoo.execute(credential(), selected, parameters={}, query={}, body=body) == {
            "result": [7]
        }


async def test_nonfinite_json_is_refused_before_an_odoo_request(transport):
    with pytest.raises(BadRequestError, match="finite JSON"):
        await odoo.execute(
            credential(),
            operation("create_contacts"),
            parameters={},
            query={},
            body={"values": {"credit_limit": float("nan")}},
        )
