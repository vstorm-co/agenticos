"""The request span carries no customer number (#2076)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.logfire_setup import SECRET_PATH_MARKER, redact_secret_arguments
from app.schemas.channel_bot import WhatsAppCustomerSearch

BOT = uuid4()
PATH = f"/api/v1/channels/bots/{BOT}/whatsapp-customers/search"
DIGITS = ("600", "700", "800")


def _request(path: str = PATH) -> MagicMock:
    request = MagicMock()
    request.url.path = path
    request.query_params = {}
    request.path_params = {"bot_id": str(BOT)}
    return request


@pytest.mark.security
@pytest.mark.parametrize("shape", ["model", "dict"])
def test_the_search_number_is_not_in_the_request_span(shape):
    body = (
        WhatsAppCustomerSearch(phone="+48 600 700 800")
        if shape == "model"
        else {"phone": "+48 600 700 800"}
    )
    attributes = {"values": {"bot_id": BOT, "data": body}, "errors": []}

    result = redact_secret_arguments(_request(), attributes)

    assert result["values"]["bot_id"] == BOT
    rendered = repr(result)
    assert not any(part in rendered for part in DIGITS)
    assert SECRET_PATH_MARKER in rendered
    assert attributes["values"]["data"] is body


@pytest.mark.security
def test_a_number_nested_in_a_list_or_mapping_is_redacted_too():
    attributes = {"values": {"data": {"filters": [{"phone": "+48 600 700 800"}], "q": "x"}}}

    result = redact_secret_arguments(_request(), attributes)

    assert not any(part in repr(result) for part in DIGITS)
    assert result["values"]["data"]["q"] == "x"


@pytest.mark.security
def test_a_malformed_number_is_not_in_the_span_either():
    attributes = {
        "values": {"bot_id": BOT},
        "errors": [
            {"loc": ("body", "phone"), "input": "+48abc600"},
            {"loc": ("body", "other"), "input": "kept"},
        ],
    }

    result = redact_secret_arguments(_request(), attributes)

    assert result["errors"] == [
        {"loc": ("body", "phone"), "input": SECRET_PATH_MARKER},
        {"loc": ("body", "other"), "input": "kept"},
    ]


def test_attributes_without_a_number_are_untouched():
    attributes = {"values": {"bot_id": BOT, "limit": 5}, "errors": []}

    assert redact_secret_arguments(_request(), attributes) is attributes


@pytest.mark.security
def test_a_body_with_no_secret_field_is_not_dumped():
    from pydantic import BaseModel

    class Filter(BaseModel):
        q: str = "x"

    body = Filter()
    attributes = {"values": {"data": body}, "errors": []}
    with patch.object(Filter, "model_dump", side_effect=AssertionError("dumped")):
        assert redact_secret_arguments(_request(), attributes) is attributes


@pytest.mark.security
def test_a_model_with_an_extra_phone_field_is_scrubbed():
    from pydantic import BaseModel, ConfigDict

    class Loose(BaseModel):
        model_config = ConfigDict(extra="allow")

    result = redact_secret_arguments(
        _request(), {"values": {"data": Loose(phone="+48 600 700 800")}, "errors": []}
    )

    assert not any(part in repr(result) for part in DIGITS)
