"""WhatsApp webhook parsing: what Meta sends, read without trusting it (#2076)."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.services.channels.base import IncomingMessage, IncomingPress
from app.services.channels.whatsapp_payload import (
    MAX_MESSAGE_AGE,
    WhatsAppMessage,
    group_by_customer,
    mask_phone,
    parse_webhook,
    platform_user_id_for,
    to_event,
    to_incoming,
    verify_signature,
)

FIXTURES = Path(__file__).parent / "fixtures" / "whatsapp"
NOW = datetime.fromtimestamp(1790000100, UTC)
ORG = UUID("11111111-1111-1111-1111-111111111111")
SECRET = "app-secret"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _parse(name: str, **kwargs: Any):
    return parse_webhook(
        _load(name), phone_number_id="PNID1", account_id="WABA1", now=kwargs.pop("now", NOW)
    )


def _sign(body: bytes, key: str) -> str:
    return "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def test_a_signature_over_the_raw_body_verifies():
    body = b'{"a": 1}'
    assert verify_signature(body, _sign(body, SECRET), SECRET) is True


def test_a_tampered_body_fails():
    body = b'{"a": 1}'
    assert verify_signature(b'{"a": 2}', _sign(body, SECRET), SECRET) is False


def test_a_missing_or_malformed_header_fails():
    body = b"{}"
    good = _sign(body, SECRET)
    assert verify_signature(body, None, SECRET) is False
    assert verify_signature(body, "", SECRET) is False
    assert verify_signature(body, good.removeprefix("sha256="), SECRET) is False
    assert verify_signature(body, "sha1=" + good.removeprefix("sha256="), SECRET) is False
    assert verify_signature(body, "sha256=zz", SECRET) is False
    assert verify_signature(body, "sha256=é", SECRET) is False


@pytest.mark.security
def test_an_empty_app_secret_never_verifies():
    body = b"{}"
    assert verify_signature(body, _sign(body, ""), "") is False


def test_a_body_signed_with_the_verify_token_fails():
    body = b"{}"
    assert verify_signature(body, _sign(body, "verify-token"), SECRET) is False


def test_a_text_message_parses():
    parsed = _parse("text")
    assert parsed.statuses == ()
    assert (parsed.foreign, parsed.stale, parsed.unidentified, parsed.ignored) == (0, 0, 0, 0)
    assert parsed.messages == (
        WhatsAppMessage(
            wamid="wamid.A1",
            bsuid="US.111",
            kind="text",
            text="hello bot",
            sent_at=datetime.fromtimestamp(1790000000, UTC),
            profile_name="Ada Lovelace",
            username="ada",
            phone="4915112345678",
            media_id=None,
            mime_type=None,
            filename=None,
        ),
    )


def test_messages_come_back_in_the_order_they_were_sent():
    parsed = _parse("two_texts_one_customer")
    assert [m.text for m in parsed.messages] == ["first", "second"]


def test_changes_for_another_number_or_account_are_counted_foreign_and_dropped():
    parsed = _parse("mixed_numbers")
    assert [m.wamid for m in parsed.messages] == ["wamid.MINE"]
    assert parsed.foreign == 2


def test_a_message_older_than_seven_days_is_dropped():
    assert MAX_MESSAGE_AGE.days == 7
    parsed = _parse("text", now=NOW + timedelta(days=8))
    assert parsed.messages == ()
    assert parsed.stale == 1
    assert _parse("text", now=NOW + timedelta(days=6)).stale == 0


def test_statuses_never_become_messages():
    parsed = _parse("statuses")
    assert parsed.messages == ()
    assert [(s.wamid, s.status, s.error_codes) for s in parsed.statuses] == [
        ("wamid.S1", "delivered", ()),
        ("wamid.S2", "failed", (131047,)),
    ]


def test_reactions_and_system_events_are_ignored_not_answered():
    parsed = _parse("reaction_and_system")
    assert parsed.messages == ()
    assert parsed.ignored == 2


def test_a_message_without_a_user_id_is_counted_not_guessed():
    parsed = _parse("no_user_id")
    assert parsed.messages == ()
    assert parsed.unidentified == 1


def test_a_location_becomes_text():
    message = _parse("location").messages[0]
    assert message.kind == "location"
    assert message.text == "Location: Office, Main St 1 (52.2, 21.0)"
    assert message.media_id is None


def test_a_location_omits_what_is_missing():
    payload = _load("location")
    value = payload["entry"][0]["changes"][0]["value"]
    value["messages"][0]["location"] = {"latitude": 1.5, "longitude": 2.5}
    parsed = parse_webhook(payload, phone_number_id="PNID1", account_id="WABA1", now=NOW)
    assert parsed.messages[0].text == "Location: (1.5, 2.5)"


def test_an_image_and_a_document_become_attachments():
    image = _parse("image").messages[0]
    assert (image.kind, image.text, image.media_id, image.mime_type) == (
        "image",
        "look",
        "MEDIA1",
        "image/jpeg",
    )
    incoming = to_incoming(image, bot_id="bot-1", organization_id=ORG)
    assert incoming.text == "look"
    [attachment] = incoming.attachments
    assert attachment.handle == "MEDIA1"
    assert attachment.mime_type == "image/jpeg"
    assert attachment.filename == "image.jpg"

    document = _parse("document").messages[0]
    assert document.text == ""
    [doc_attachment] = to_incoming(document, bot_id="bot-1", organization_id=ORG).attachments
    assert doc_attachment.handle == "MEDIA2"
    assert doc_attachment.filename == "report.pdf"


def test_a_media_kind_with_an_unknown_mime_type_keeps_its_bare_name():
    message = WhatsAppMessage(
        wamid="w", bsuid="US.1", kind="audio", text="", sent_at=NOW,
        profile_name=None, username=None, phone=None,
        media_id="M", mime_type=None, filename=None,
    )  # fmt: skip
    [attachment] = to_incoming(message, bot_id="b", organization_id=ORG).attachments
    assert attachment.filename == "audio"
    assert attachment.mime_type == "application/octet-stream"


def test_a_contact_card_becomes_a_named_unreadable_attachment():
    message = _parse("contacts").messages[0]
    assert message.text == ""
    assert message.media_id is None
    [attachment] = to_incoming(message, bot_id="bot-1", organization_id=ORG).attachments
    assert attachment.filename == "contacts message"
    assert attachment.mime_type == "application/octet-stream"
    assert attachment.handle == "wamid.CON1"


def test_a_sticker_is_a_named_message_not_a_file():
    payload = _load("image")
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message["type"] = "sticker"
    message["sticker"] = {"id": "STK1", "mime_type": "image/webp"}
    del message["image"]
    parsed = parse_webhook(payload, phone_number_id="PNID1", account_id="WABA1", now=NOW)
    [parsed_message] = parsed.messages
    assert parsed_message.media_id is None
    [attachment] = to_incoming(parsed_message, bot_id="b", organization_id=ORG).attachments
    assert attachment.filename == "sticker message"
    assert attachment.mime_type == "application/octet-stream"
    assert attachment.handle == parsed_message.wamid


def test_grouping_keeps_customers_apart_and_each_in_order():
    def msg(wamid: str, bsuid: str, minute: int) -> WhatsAppMessage:
        return WhatsAppMessage(
            wamid=wamid, bsuid=bsuid, kind="text", text=wamid,
            sent_at=NOW + timedelta(minutes=minute),
            profile_name=None, username=None, phone=None,
            media_id=None, mime_type=None, filename=None,
        )  # fmt: skip

    groups = group_by_customer(
        [msg("a2", "A", 2), msg("b1", "B", 1), msg("a1", "A", 0), msg("b2", "B", 3)]
    )
    assert [[m.wamid for m in g] for g in groups] == [["a1", "a2"], ["b1", "b2"]]
    assert group_by_customer([]) == []


def test_identity_is_namespaced_by_organization():
    message = _parse("text").messages[0]
    incoming = to_incoming(message, bot_id="bot-1", organization_id=ORG)
    assert platform_user_id_for(ORG, "US.111") == f"{ORG}:US.111"
    assert incoming.platform == "whatsapp"
    assert incoming.bot_id == "bot-1"
    assert incoming.platform_user_id == f"{ORG}:US.111"
    assert incoming.platform_chat_id == "US.111"
    assert incoming.chat_type == "private"
    assert incoming.message_id == "wamid.A1"
    assert incoming.platform_display_name == "Ada Lovelace"
    assert incoming.text == "hello bot"
    assert incoming.attachments == []


def test_the_phone_number_is_masked_and_never_in_raw():
    assert mask_phone("4915112345678") == "•••• 5678"
    assert mask_phone("+49 151 1234 5678") == "•••• 5678"
    assert mask_phone("123") is None
    assert mask_phone(None) is None

    message = _parse("text").messages[0]
    incoming = to_incoming(message, bot_id="bot-1", organization_id=ORG)
    assert incoming.raw == {}
    assert incoming.platform_username == "ada"

    without_username = WhatsAppMessage(
        wamid="w", bsuid="US.1", kind="text", text="x", sent_at=NOW,
        profile_name=None, username=None, phone="4915112345678",
        media_id=None, mime_type=None, filename=None,
    )  # fmt: skip
    masked = to_incoming(without_username, bot_id="b", organization_id=ORG)
    assert masked.platform_username == "•••• 5678"
    assert "4915112345678" not in repr(masked)


def test_garbage_never_raises():
    garbage: list[Any] = [
        {},
        {"entry": "x"},
        {"entry": [1, None, {"changes": "y"}]},
        {"entry": [{"id": "WABA1", "changes": [{"field": "messages", "value": "z"}]}]},
        {"entry": [{"id": "WABA1", "changes": [3, {"field": "other", "value": {}}]}]},
    ]
    for payload in garbage:
        parsed = parse_webhook(payload, phone_number_id="PNID1", account_id="WABA1", now=NOW)
        assert parsed.messages == ()


def test_malformed_messages_are_counted_unidentified():
    payload = _load("text")
    value = payload["entry"][0]["changes"][0]["value"]
    base = value["messages"][0]
    value["messages"] = [
        "not a dict",
        {**base, "id": ""},
        {**base, "timestamp": "soon"},
        {**base, "type": 7},
        {**base, "text": "no body mapping"},
        {**base, "text": {"body": 5}},
        {**base, "from_user_id": None, "user_id": None},
    ]
    value["statuses"] = [
        "bad",
        {"id": "x"},
        {"id": "w", "status": "failed", "errors": ["e", {"code": "x"}, {"code": 7}]},
    ]
    parsed = parse_webhook(payload, phone_number_id="PNID1", account_id="WABA1", now=NOW)
    assert parsed.messages == ()
    assert parsed.unidentified == 7
    assert [(s.wamid, s.error_codes) for s in parsed.statuses] == [("w", (7,))]


def test_user_id_and_contact_fallbacks():
    payload = _load("text")
    value = payload["entry"][0]["changes"][0]["value"]
    message = value["messages"][0]
    message["user_id"] = message.pop("from_user_id")
    message["from"] = "4915100000000"
    value["contacts"] = ["junk", {"user_id": "other", "profile": {"name": "N"}}]
    parsed = parse_webhook(payload, phone_number_id="PNID1", account_id="WABA1", now=NOW)
    [parsed_message] = parsed.messages
    assert parsed_message.bsuid == "US.111"
    assert parsed_message.phone == "4915100000000"
    assert parsed_message.profile_name is None


def test_a_media_message_without_a_body_mapping_is_still_a_media_message():
    payload = _load("image")
    value = payload["entry"][0]["changes"][0]["value"]
    value["messages"][0]["image"] = {"id": "M", "caption": 5}
    parsed = parse_webhook(payload, phone_number_id="PNID1", account_id="WABA1", now=NOW)
    [message] = parsed.messages
    assert (message.media_id, message.text, message.mime_type) == ("M", "", None)


def test_media_type_parameters_do_not_reach_the_attachment():
    payload = _load("image")
    value = payload["entry"][0]["changes"][0]["value"]
    message = value["messages"][0]
    message["type"] = "audio"
    message["audio"] = {"id": "M", "mime_type": "audio/ogg; codecs=opus"}
    del message["image"]
    parsed = parse_webhook(payload, phone_number_id="PNID1", account_id="WABA1", now=NOW)
    [parsed_message] = parsed.messages
    assert parsed_message.mime_type == "audio/ogg; codecs=opus"
    [attachment] = to_incoming(parsed_message, bot_id="b", organization_id=ORG).attachments
    assert (attachment.filename, attachment.mime_type) == ("audio.ogg", "audio/ogg")


def test_a_media_message_without_a_media_id_is_unidentified():
    payload = _load("image")
    value = payload["entry"][0]["changes"][0]["value"]
    del value["messages"][0]["image"]["id"]
    parsed = parse_webhook(payload, phone_number_id="PNID1", account_id="WABA1", now=NOW)
    assert parsed.messages == ()
    assert parsed.unidentified == 1


@pytest.mark.security
def test_the_phone_number_stays_out_of_a_messages_repr():
    message = _parse("text").messages[0]
    assert message.phone == "4915112345678"
    assert "4915112345678" not in repr(message)


def _event(name: str):
    (message,) = _parse(name).messages
    return message, to_event(message, bot_id="bot-1", organization_id=ORG)


def test_a_button_reply_is_a_press():
    message, press = _event("button_reply")

    assert (message.kind, message.text) == ("interactive", "Approve")
    assert isinstance(press, IncomingPress)
    assert press.platform == "whatsapp"
    assert press.bot_id == "bot-1"
    assert press.platform_user_id == f"{ORG}:US.111"
    assert press.platform_chat_id == "US.111"
    assert press.value == "aos:0123456789abcdef0123456789abcdef:0"
    assert press.platform_username == "ada"
    assert press.message_id == "wamid.PROMPT1"
    assert press.ack_id == "wamid.TAP1"


def test_a_list_reply_is_a_press():
    _, press = _event("list_reply")

    assert isinstance(press, IncomingPress)
    assert press.value == "aos:0123456789abcdef0123456789abcdef:2"
    assert press.message_id == "wamid.PROMPT2"
    assert press.delivery_id == "wamid.TAP2"
    assert press.ack_id == "wamid.TAP2"


def test_a_reply_that_names_no_prompt_is_still_a_press():
    payload = _load("button_reply")
    del payload["entry"][0]["changes"][0]["value"]["messages"][0]["context"]
    (message,) = parse_webhook(
        payload, phone_number_id="PNID1", account_id="WABA1", now=NOW
    ).messages

    press = to_event(message, bot_id="b", organization_id=ORG)

    assert isinstance(press, IncomingPress)
    assert press.message_id is None


def test_an_unknown_interactive_type_stays_a_named_message():
    message, event = _event("interactive_unknown")

    assert (message.reply_id, message.context_id) == (None, None)
    assert isinstance(event, IncomingMessage)
    assert [a.filename for a in event.attachments] == ["interactive message"]


def test_a_reply_with_no_id_stays_a_named_message():
    payload = _load("button_reply")
    reply = payload["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"]
    del reply["button_reply"]["id"]
    (message,) = parse_webhook(
        payload, phone_number_id="PNID1", account_id="WABA1", now=NOW
    ).messages

    assert isinstance(to_event(message, bot_id="b", organization_id=ORG), IncomingMessage)


def test_a_text_message_is_an_incoming_message_either_way():
    (message,) = _parse("text").messages

    assert to_event(message, bot_id="b", organization_id=ORG) == to_incoming(
        message, bot_id="b", organization_id=ORG
    )


def test_a_template_button_tap_is_read_as_its_text():
    [message] = _parse("template_button").messages
    assert message.kind == "button"
    assert message.text == "Show me"
    assert message.reply_id is None
    incoming = to_incoming(message, bot_id="b", organization_id=ORG)
    assert incoming.text == "Show me"
    assert incoming.attachments == []
    assert isinstance(to_event(message, bot_id="b", organization_id=ORG), IncomingMessage)


def test_a_button_tap_with_no_text_stays_a_named_message():
    payload = _load("template_button")
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["button"] = {}
    [message] = parse_webhook(
        payload, phone_number_id="PNID1", account_id="WABA1", now=NOW
    ).messages
    assert message.text == ""
    [attachment] = to_incoming(message, bot_id="b", organization_id=ORG).attachments
    assert attachment.filename == "button message"
