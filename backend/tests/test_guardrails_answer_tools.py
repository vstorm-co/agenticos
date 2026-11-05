"""Output guardrails screen the tools whose arguments the person is shown."""

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import (
    AgentStreamEvent,
    ModelResponse,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    ToolCallPart,
    ToolCallPartDelta,
)

from app.agents.capabilities import CapabilityBinding, ToolOverride
from app.agents.capabilities.guardrails import (
    ANSWER_TOOLS_RESOURCE,
    GuardrailBlocked,
    GuardrailsConfig,
    answer_tools,
    build_guardrails,
    output_screen,
)
from app.agents.capabilities.guardrails._capability import (
    _BLOCK_MESSAGE,
    ANSWER_MARKUP_FIELDS,
    ANSWER_SKIPPED_FIELDS,
    ScreenedToolArgs,
    _edge_detector,
)

pytestmark = pytest.mark.anyio

SECRET = "sk-ant-api03-ABCDEFGHIJKLMNOPQR"
REDACTED = "[redacted:anthropic_key]"
DRAFT_ARGS = '{"title": "t", "kind": "Email", "versions": [{"fields": [{"text": "key %s"}]}]}'


def _screen(*, keywords: list[str] | None = None, tools: frozenset[str] | None = None):
    return ScreenedToolArgs(
        screen=_edge_detector(
            redact_secrets_on=keywords is None,
            redact_pii_on=False,
            phone_regions=(),
            keywords=keywords or [],
            edge="output",
        ),
        tools=tools,
    )


async def _after(screen: ScreenedToolArgs, *parts: ToolCallPart) -> ModelResponse:
    return await screen.after_model_request(
        MagicMock(), request_context=MagicMock(), response=ModelResponse(parts=list(parts))
    )


async def _released(screen: ScreenedToolArgs, *events: AgentStreamEvent) -> list[AgentStreamEvent]:
    async def source() -> AsyncIterator[AgentStreamEvent]:
        for event in events:
            yield event

    return [e async for e in screen.wrap_run_event_stream(MagicMock(), stream=source())]


def _split_call(final: str, args: str) -> list[AgentStreamEvent]:
    first, rest = final[:5], final[5:]
    return [
        PartStartEvent(index=0, part=ToolCallPart(tool_name=first, args="")),
        PartDeltaEvent(index=0, delta=ToolCallPartDelta(tool_name_delta=rest, args_delta=args)),
        PartEndEvent(index=0, part=ToolCallPart(tool_name=final, args=args)),
    ]


@pytest.mark.security
async def test_a_listed_call_is_redacted_and_another_tools_call_is_not():
    screen = _screen(tools=frozenset({"write_draft"}))
    draft = ToolCallPart(tool_name="write_draft", args=DRAFT_ARGS % SECRET)
    other = ToolCallPart(tool_name="send_email", args=DRAFT_ARGS % SECRET)

    out = await _after(screen, draft, other)

    assert REDACTED in str(out.parts[0].args)
    assert SECRET not in str(out.parts[0].args)
    assert out.parts[1].args == DRAFT_ARGS % SECRET


@pytest.mark.security
async def test_a_draft_with_a_blocked_keyword_is_refused_as_an_output():
    screen = _screen(keywords=["acme-secret"], tools=frozenset({"write_draft"}))
    draft = ToolCallPart(tool_name="write_draft", args=DRAFT_ARGS % "acme-secret")

    with pytest.raises(GuardrailBlocked) as blocked:
        await _after(screen, draft)

    assert blocked.value.edge == "output"
    assert str(blocked.value) == _BLOCK_MESSAGE["output"]


@pytest.mark.security
async def test_a_name_that_arrives_in_pieces_is_held_until_it_is_whole():
    screen = _screen(tools=frozenset({"write_draft"}))
    events = _split_call("write_draft", DRAFT_ARGS % SECRET)

    out = await _released(screen, *events)

    assert [type(e) for e in out] == [PartStartEvent, PartEndEvent]
    assert SECRET not in repr(out)
    assert REDACTED in repr(out)


async def test_a_split_name_that_ends_as_another_tool_is_released_unchanged():
    screen = _screen(tools=frozenset({"write_draft"}))
    events = _split_call("write_file", DRAFT_ARGS % SECRET)

    assert await _released(screen, *events) == events


async def test_a_call_that_could_never_be_listed_streams_as_it_arrives():
    screen = _screen(tools=frozenset({"write_draft"}))
    events = [
        PartStartEvent(index=0, part=ToolCallPart(tool_name="send_email", args="")),
        PartDeltaEvent(index=0, delta=ToolCallPartDelta(args_delta="{}")),
        PartEndEvent(index=0, part=ToolCallPart(tool_name="send_email", args="{}")),
    ]

    assert await _released(screen, *events) == events


@pytest.mark.security
async def test_malformed_arguments_stay_a_string_when_a_secret_is_redacted():
    for screen in (_screen(), _screen(tools=frozenset({"write_draft"}))):
        bad = ToolCallPart(tool_name="write_draft", args=f'{{"text": "{SECRET}')

        out = await _after(screen, bad)

        (call,) = out.parts
        assert isinstance(call, ToolCallPart)
        assert isinstance(call.args, str)
        assert REDACTED in call.args
        assert SECRET not in call.args


async def test_malformed_arguments_that_hold_nothing_to_redact_are_left_alone():
    bad = ToolCallPart(tool_name="t", args='{"text": ')

    out = await _after(_screen(), bad)

    assert out.parts[0] is bad


def test_the_output_edge_screens_the_answer_tools_too():
    built = build_guardrails(
        GuardrailsConfig(redact_secrets_out=True), answer_tools=frozenset({"write_draft"})
    )
    assert built is not None
    (extra,) = [e for e in built.capabilities if isinstance(e, ScreenedToolArgs)]
    assert extra.tools == frozenset({"write_draft"})


def test_the_composition_hands_the_screen_its_markup_and_skipped_fields():
    built = build_guardrails(
        GuardrailsConfig(redact_secrets_out=True), answer_tools=frozenset({"draw"})
    )
    assert built is not None
    (extra,) = [e for e in built.capabilities if isinstance(e, ScreenedToolArgs)]
    assert extra.markup == ANSWER_MARKUP_FIELDS
    assert extra.skip == ANSWER_SKIPPED_FIELDS


async def test_a_listed_call_with_a_blocked_keyword_is_withheld_from_the_stream():
    screen = _screen(keywords=["acme-secret"], tools=frozenset({"write_draft"}))

    assert await _released(screen, *_split_call("write_draft", DRAFT_ARGS % "acme-secret")) == []


def test_without_answer_tools_the_composition_is_unchanged():
    built = build_guardrails(GuardrailsConfig(redact_secrets_out=True))
    assert built is not None
    assert not any(isinstance(e, ScreenedToolArgs) for e in built.capabilities)


def test_an_agent_with_no_output_edge_gets_no_answer_screen():
    built = build_guardrails(
        GuardrailsConfig(redact_secrets_args=True), answer_tools=frozenset({"write_draft"})
    )
    assert built is not None
    assert [e.tools for e in built.capabilities if isinstance(e, ScreenedToolArgs)] == [None]


def test_the_answer_tools_are_the_drafts_tool_under_its_effective_name():
    assert answer_tools([CapabilityBinding(capability_id="drafts")]) == {"write_draft"}
    renamed = CapabilityBinding(
        capability_id="drafts",
        tool_overrides={"write_draft": ToolOverride(name="compose_reply")},
    )
    assert answer_tools([renamed]) == {"compose_reply"}
    off = CapabilityBinding(capability_id="drafts", enabled=False)
    assert answer_tools([off, CapabilityBinding(capability_id="clock")]) == frozenset()


def test_every_tool_that_shows_the_person_something_is_an_answer_tool():
    bindings = [
        CapabilityBinding(capability_id=cid)
        for cid in ("drafts", "visuals", "charts", "artifacts", "ask_user")
    ]

    assert answer_tools(bindings) == {
        "write_draft",
        "draw",
        "revise_visual",
        "create_chart",
        "publish_artifact",
        "ask_user_question",
    }


def test_only_the_publishing_tool_of_the_artifacts_capability_is_an_answer_tool() -> None:
    assert answer_tools([CapabilityBinding(capability_id="artifacts")]) == {"publish_artifact"}


def _pii_screen() -> ScreenedToolArgs:
    return ScreenedToolArgs(
        screen=output_screen(GuardrailsConfig(redact_secrets_out=True, redact_pii_out=True)).screen,
        tools=frozenset({"draw", "create_chart"}),
        markup=ANSWER_MARKUP_FIELDS,
        skip=ANSWER_SKIPPED_FIELDS,
    )


@pytest.mark.security
async def test_a_drawings_source_keeps_its_numbers_and_its_words_are_screened():
    svg = (
        '<svg viewBox="0 0 240 135"><path d="M120 46.5L195.7 90.2 120 133.8 44.3 90.2 '
        f'1957 902 12 1338"/><text>Call +48 601 234 567, key {SECRET}</text></svg>'
    )
    call = ToolCallPart(tool_name="draw", args={"title": "Map", "kind": "svg", "content": svg})

    out = await _after(_pii_screen(), call)

    (shown,) = out.parts
    content = shown.args["content"]
    assert 'viewBox="0 0 240 135"' in content
    assert "M120 46.5L195.7 90.2 120 133.8 44.3 90.2 1957 902 12 1338" in content
    assert "601 234 567" not in content
    assert SECRET not in content


@pytest.mark.security
async def test_a_charts_numbers_stay_numbers_and_its_labels_are_screened():
    args = {
        "chart_type": "line",
        "title": f"Key {SECRET}",
        "x_values": ["Q1", 2.5],
        "series": [{"name": "Rev", "values": [1.5, 2, 3.25]}],
    }

    out = await _after(_pii_screen(), ToolCallPart(tool_name="create_chart", args=args))

    (shown,) = out.parts
    assert shown.args["title"] == "Key " + REDACTED
    assert shown.args["x_values"] == ["Q1", 2.5]
    assert shown.args["series"][0]["values"] == [1.5, 2, 3.25]


async def test_markdown_with_no_tag_in_it_is_screened_whole():
    call = ToolCallPart(tool_name="draw", args={"content": f"key {SECRET}"})

    out = await _after(_pii_screen(), call)

    assert out.parts[0].args == {"content": "key " + REDACTED}


async def test_a_style_block_and_an_identifier_field_are_left_as_written():
    args = {
        "visual_id": "1234567890",
        "content": "<style>a{margin:1957 902 12 1338}</style><b>hi</b>",
        "kind": "html",
    }

    out = await _after(_pii_screen(), ToolCallPart(tool_name="draw", args=args))

    assert out.parts[0].args == args


def test_the_resource_key_is_a_stable_name():
    assert ANSWER_TOOLS_RESOURCE == "answer_tools"


async def test_an_identifier_field_is_not_screened_even_when_it_looks_like_personal_data():
    args = {
        "visual_id": "123-45-6789",
        "images": [{"name": "logo", "source": "reports/123-45-6789.png"}],
        "path": "out/123-45-6789.html",
        "title": "Map",
    }

    out = await _after(_pii_screen(), ToolCallPart(tool_name="draw", args=args))

    assert out.parts[0].args == args


async def _drawn(content: str, key: str = "content") -> str:
    out = await _after(_pii_screen(), ToolCallPart(tool_name="draw", args={key: content}))
    return out.parts[0].args[key]


PHONE = "+48 601 234 567"


@pytest.mark.security
async def test_text_before_the_first_tag_is_screened():
    shown = await _drawn(f"# Report\n\nkey {SECRET}\n<br>tail")

    assert SECRET not in shown
    assert shown.endswith("<br>tail")


@pytest.mark.security
async def test_a_mermaid_label_is_screened_around_its_break():
    shown = await _drawn(f"A[call {PHONE}<br/>now]")

    assert "601 234 567" not in shown
    assert shown.endswith("<br/>now]")


@pytest.mark.security
async def test_an_edit_fragment_that_ends_in_a_closing_tag_is_screened():
    shown = await _drawn(f"Call {PHONE} now</b>", key="new")

    assert "601 234 567" not in shown
    assert shown.endswith(" now</b>")


@pytest.mark.security
async def test_text_after_a_stray_angle_bracket_is_screened():
    shown = await _drawn(f"<p>a < b with {SECRET}</p>")

    assert SECRET not in shown
    assert shown.startswith("<p>a < b with ")


@pytest.mark.security
async def test_readable_attributes_are_screened_and_the_rest_of_the_tag_is_not():
    shown = await _drawn(
        f'<img alt="{PHONE}" title=\'{PHONE}\' aria-label="{PHONE}" '
        f'placeholder="{PHONE}" value="{PHONE}" width="120" data-title="{PHONE}">'
    )

    assert shown.count("601 234 567") == 1
    assert 'width="120"' in shown
    assert f'data-title="{PHONE}"' in shown


@pytest.mark.security
async def test_cdata_text_is_screened():
    shown = await _drawn(f"<text><![CDATA[key {SECRET}]]></text>")

    assert SECRET not in shown
    assert shown.startswith("<text><![CDATA[key ")
    assert shown.endswith("]]></text>")


@pytest.mark.security
async def test_a_script_string_is_screened_and_its_code_is_not():
    shown = await _drawn(
        f"<script>var x = 120 46 5195; var s = \"key {SECRET}\"; var t = '{PHONE}'; "
        f"var u = `{PHONE}`; var v = `a${{x}} {PHONE}`;</script>"
    )

    assert "var x = 120 46 5195;" in shown
    assert "a${x} " in shown
    assert SECRET not in shown
    assert "601 234 567" not in shown


async def test_a_comment_and_a_style_block_are_left_as_written():
    source = f"<!-- {PHONE} --><style>a{{margin:1957 902 12 1338}} /* {PHONE} */</style><b>x</b>"

    assert await _drawn(source) == source


@pytest.mark.security
async def test_a_blocked_keyword_anywhere_in_markup_ends_the_run():
    screen = _screen(keywords=["acme-secret"], tools=frozenset({"draw"}))
    screen = ScreenedToolArgs(screen=screen.screen, tools=screen.tools, markup=ANSWER_MARKUP_FIELDS)
    call = ToolCallPart(tool_name="draw", args={"content": "acme-secret <br> x"})

    with pytest.raises(GuardrailBlocked) as blocked:
        await _after(screen, call)

    assert str(blocked.value) == _BLOCK_MESSAGE["output"]


@pytest.mark.security
async def test_identifiers_nested_under_a_skipped_field_are_left_as_written():
    args = {
        "bindings": {"rows": {"table": "ops@acme.com list"}},
        "actions": [{"workflow": "Mail ops@acme.com"}],
    }

    out = await _after(_pii_screen(), ToolCallPart(tool_name="draw", args=args))

    assert out.parts[0].args == args


@pytest.mark.security
@pytest.mark.parametrize(
    "source",
    [
        "Write to <jan@acme.com> today",
        "Jan Kowalski <jan@acme.com>",
        f"See <https://acme.io/hook?k={SECRET}>",
    ],
)
async def test_an_autolink_is_text_and_is_screened(source: str):
    shown = await _drawn(source)

    assert "jan@acme.com" not in shown
    assert SECRET not in shown


@pytest.mark.security
async def test_a_closing_angle_inside_a_quoted_attribute_does_not_end_the_tag():
    shown = await _drawn(f'<img alt="key {SECRET} > x" width="120"><b>y</b>')

    assert SECRET not in shown
    assert 'width="120"><b>y</b>' in shown


@pytest.mark.security
async def test_an_unquoted_readable_attribute_is_screened():
    shown = await _drawn("<img alt=jan@acme.com width=120>")

    assert "jan@acme.com" not in shown
    assert "width=120>" in shown


@pytest.mark.security
@pytest.mark.parametrize("attribute", ["aria-description", "label", "href", "src"])
async def test_more_readable_attributes_are_screened(attribute: str):
    shown = await _drawn(f'<a {attribute}="https://acme.io/?k={SECRET}" id="x">y</a>')

    assert SECRET not in shown
    assert 'id="x">y</a>' in shown


async def test_a_fragment_link_and_a_tag_with_no_words_are_left_as_written():
    source = '<svg viewBox="0 0 240 135"><use href="#marker"/><my-el data-x="1 > 0"></my-el></svg>'

    assert await _drawn(source) == source


_KEPT = [
    '<svg viewBox="0 0 240 135">',
    '<path d="M120 46.5L195.7 90.2 120 133.8 44.3 90.2 1957 902 12 1338"/>',
    "</g>",
    "<br/>",
    '<my-el data-x="1 > 0">',
    "<!DOCTYPE html>",
    "<!-- 1957 902 12 1338 -->",
    "<style>a{margin:1957 902 12 1338}</style>",
    '<?xml version="1.0"?>',
    "<img src=\"data:image/svg+xml;utf8,<svg><path d='M1957 902 12 1338'/></svg>\">",
    "<a href='DATA:text/plain;base64,MTk1NyA5MDIgMTIgMTMzOA==' id=x>y</a>",
    "<img src=data:image/png;base64,QUJDLTEyMy00NS02Nzg5>",
]
_CARRIERS = [
    f" note {SECRET} ",
    f"<https://acme.io/?k={SECRET}>",
    f'<img alt="a > {SECRET}">',
    f"<img alt={SECRET}>",
    f'<script>var s = "{SECRET}";</script>',
    f"<![CDATA[{SECRET}]]>",
    f"<script>var t = `${{a}} {SECRET}`;</script>",
    f" a < {SECRET} ",
    f"A[{SECRET}<br/>x]",
]


@pytest.mark.security
async def test_generated_markup_never_shows_a_secret_and_keeps_its_markup():
    """Several hundred documents mixing markup that must pass through untouched
    with every kind of place a person reads text: no secret survives, and every
    piece of markup survives byte for byte."""
    import random

    rng = random.Random(2737)
    for _ in range(400):
        pieces = [rng.choice(_KEPT + _CARRIERS) for _ in range(rng.randint(1, 8))]
        shown = await _drawn("".join(pieces))

        assert SECRET not in shown, pieces
        for kept in _KEPT:
            assert shown.count(kept) >= sum(piece == kept for piece in pieces), (kept, pieces)


@pytest.mark.security
async def test_a_template_expression_with_nested_braces_stays_code_and_its_text_is_screened():
    shown = await _drawn(f"<script>var t = `${{ {{a: 1}}.a }} key {SECRET}`;</script>")

    assert "${ {a: 1}.a }" in shown
    assert SECRET not in shown


@pytest.mark.security
async def test_a_template_expression_that_never_closes_is_screened_as_text():
    shown = await _drawn(f"<script>var t = `${{ key {SECRET}`;</script>")

    assert SECRET not in shown


@pytest.mark.parametrize(
    "source",
    [
        "<img src=\"data:image/svg+xml;utf8,<svg><path d='M1957 902 12 1338'/></svg>\">",
        '<img src=" data:image/png;base64,MTIzLTQ1LTY3ODkgKzQ4IDYwMSAyMzQgNTY3">',
    ],
)
async def test_a_data_uri_is_encoded_content_and_is_left_as_written(source: str):
    assert await _drawn(source) == source


@pytest.mark.security
async def test_a_text_data_uri_is_read_as_text_and_is_screened():
    shown = await _drawn(f"<a href='data:text/plain,key {SECRET}'>x</a>")

    assert SECRET not in shown
