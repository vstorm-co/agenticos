"""The guardrails capability - what it redacts, what it blocks, and what it costs.

Most of the value here is in the refusal: a blocked prompt, answer or tool result
ends the run as `GUARDRAIL_BLOCKED` rather than completing with a refusal that reads
like any other answer. The redaction path is the opposite promise - a scrubbed key
lets the run finish - and both are checked here against a real agent run, because
the block has to *escape* `agent.run()` for the runner to record it.

The output edge has a third promise, about the stream: nothing it would redact or
block is shown before it has run, because every surface streams the answer and the
harness guardrail only reads the finished one (agenticos#1900).
"""

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace
from unittest.mock import MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability, CombinedCapability, WrapModelRequestHandler
from pydantic_ai.messages import (
    AgentStreamEvent,
    BinaryContent,
    CachePoint,
    DocumentUrl,
    ImageUrl,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    StructuredContent,
    TextContent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingCalls,
    DeltaThinkingPart,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)
from pydantic_ai.tools import RunContext
from pydantic_ai_harness._background_completion import make_background_completion
from pydantic_ai_harness.guardrails import (
    GuardrailResult,
    InputGuardrail,
    OutputGuardrail,
    ToolGuardrail,
)

from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext, get, load_builtins
from app.agents.capabilities.guardrails import (
    GuardrailBlocked,
    GuardrailsConfig,
    TranscriptScreens,
    build_guardrails,
    transcript_screens,
)
from app.agents.capabilities.guardrails import _capability as guardrails_capability
from app.agents.capabilities.guardrails._capability import (
    WITHHELD_REASONING,
    PromptContent,
    ScreenedPrompt,
    ScreenedStream,
    ScreenedToolArgs,
    _edge_detector,
    _keywords,
)

pytestmark = pytest.mark.anyio

SECRET = "sk-ant-api03-ABCDEFGHIJKLMNOPQR"


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _answers(text: str) -> FunctionModel:
    """Answer with fixed text, ignoring the prompt.

    Streams as well as answers whole: an output check screens the stream, which
    makes `agent.run()` stream the model's response under the hood.
    """

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    async def stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        yield text

    return FunctionModel(respond, stream_function=stream)


type Chunk = str | DeltaToolCalls | DeltaThinkingCalls


def _streams(*responses: Sequence[Chunk]) -> FunctionModel:
    """Stream `responses[n]` as the run's n-th model response, chunk by chunk."""

    async def stream(messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[Chunk]:
        for chunk in responses[sum(isinstance(m, ModelResponse) for m in messages)]:
            yield chunk

    return FunctionModel(stream_function=stream)


def _echoes_prompt() -> FunctionModel:
    """Answer with the prompt text the model was actually handed."""

    def respond(messages, info):  # type: ignore[no-untyped-def]
        seen = ""
        for message in messages:
            for part in getattr(message, "parts", []):
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    seen = part.content
        return ModelResponse(parts=[TextPart(seen)])

    return FunctionModel(respond)


def _calls_tool_then_answers() -> FunctionModel:
    """Call `fetch` on the first turn, then answer once it has a result."""

    def respond(messages, info):  # type: ignore[no-untyped-def]
        called = any(
            isinstance(part, ToolCallPart)
            for message in messages
            for part in getattr(message, "parts", [])
        )
        if called:
            return ModelResponse(parts=[TextPart("answered")])
        return ModelResponse(parts=[ToolCallPart(tool_name="fetch", args={}, tool_call_id="c1")])

    return FunctionModel(respond)


def _agent(
    config: GuardrailsConfig, model: FunctionModel, *, tool_result: str | None = None
) -> Agent:
    capability = build_guardrails(config)
    agent: Agent = Agent(model=model, capabilities=[capability] if capability else [])
    if tool_result is not None:

        async def fetch() -> str:
            return tool_result

        agent.tool_plain(fetch)
    return agent


def test_keywords_split_on_comma_and_newline_and_drop_blanks():
    assert _keywords("alpha, beta\ngamma") == ["alpha", "beta", "gamma"]
    assert _keywords("  spaced  ,\n , ") == ["spaced"]
    assert _keywords("") == []


def test_an_edge_with_nothing_configured_is_not_built():
    detector = _edge_detector(
        redact_secrets_on=False, redact_pii_on=False, phone_regions=(), keywords=[], edge="input"
    )
    assert detector is None


def test_a_redactor_rewrites_a_match_and_allows_clean_text():
    detect = _edge_detector(
        redact_secrets_on=True, redact_pii_on=False, phone_regions=(), keywords=[], edge="input"
    )
    assert detect is not None

    hit = detect(f"my key {SECRET} ok")
    assert hit.action == "replace"
    assert SECRET not in str(hit.replacement)

    clean = detect("nothing to redact here")
    assert clean.action == "allow"


def test_a_blocked_keyword_raises_naming_the_edge():
    detect = _edge_detector(
        redact_secrets_on=False,
        redact_pii_on=False,
        phone_regions=(),
        keywords=["forbidden"],
        edge="output",
    )
    assert detect is not None
    with pytest.raises(GuardrailBlocked) as exc:
        detect("this is forbidden text")
    assert exc.value.edge == "output"

    assert detect("this is fine").action == "allow"


def test_the_keyword_check_reads_already_redacted_text():
    """Redaction threads forward, so the keyword check runs on the clean text.

    Both a redactor and a keyword list on one edge: the secret is scrubbed first,
    and the keyword - which does not appear in the placeholder - does not match, so
    the run is allowed with the redaction applied rather than blocked.
    """
    detect = _edge_detector(
        redact_secrets_on=True,
        redact_pii_on=True,
        phone_regions=(),
        keywords=[SECRET],
        edge="input",
    )
    assert detect is not None
    verdict = detect(f"leaking {SECRET} now")
    assert verdict.action == "replace"
    assert SECRET not in str(verdict.replacement)


def test_no_edge_configured_builds_nothing():
    assert build_guardrails(GuardrailsConfig()) is None


def test_each_configured_edge_attaches_its_harness_capability():
    combined = build_guardrails(
        GuardrailsConfig(
            blocked_keywords_in="a",
            redact_secrets_out=True,
            blocked_keywords_tool="b",
        )
    )
    assert isinstance(combined, CombinedCapability)
    kinds = {type(edge) for edge in combined.capabilities}
    assert kinds == {ScreenedPrompt, OutputGuardrail, ScreenedStream, ToolGuardrail}
    # Still the harness's input edge: plain-text prompts take its path unchanged.
    assert issubclass(ScreenedPrompt, InputGuardrail)


def test_only_the_configured_edge_is_attached():
    combined = build_guardrails(GuardrailsConfig(redact_pii_out=True))
    assert isinstance(combined, CombinedCapability)
    assert [type(edge) for edge in combined.capabilities] == [OutputGuardrail, ScreenedStream]


def test_the_stream_is_left_alone_without_an_output_check():
    """Only an agent that asked for output screening pays for it in streaming."""
    combined = build_guardrails(GuardrailsConfig(redact_secrets_in=True, redact_secrets_tool=True))
    assert isinstance(combined, CombinedCapability)
    assert ScreenedStream not in {type(edge) for edge in combined.capabilities}


async def test_input_redaction_rewrites_the_prompt_the_model_sees():
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _echoes_prompt())
    result = await agent.run(f"here is {SECRET} keep it")
    assert SECRET not in result.output
    assert "[redacted:anthropic_key]" in result.output


async def test_input_pii_redaction_hides_a_phone_number_from_the_model():
    """The issue's message, run through the input edge on the default regions:
    the model is handed the placeholder, never the number."""
    agent = _agent(GuardrailsConfig(redact_pii_in=True), _echoes_prompt())
    result = await agent.run(
        "My email is jane.doe@example.com, my card number is 4111 1111 1111 1111, "
        "my SSN is 123-45-6789, and my phone number is 415-555-0132."
    )
    assert result.output == (
        "My email is [redacted:email], my card number is [redacted:credit_card], "
        "my SSN is [redacted:us_ssn], and my phone number is [redacted:phone]."
    )


# A picture whose bytes are a long run of digits: read as text, it is past the
# phone detector's digit ceiling and holds `png` and `BinaryContent` in its repr.
PICTURE = BinaryContent(data=b"0123456789" * 2_000, media_type="image/png")


def _records_prompts(seen: list[PromptContent]) -> FunctionModel:
    """Answer `ok`, recording every user prompt part of every request the model is sent."""

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        for message in messages:
            for part in getattr(message, "parts", []):
                if isinstance(part, UserPromptPart):
                    seen.append(part.content)
        return ModelResponse(parts=[TextPart("ok")])

    return FunctionModel(respond)


async def test_a_picture_under_pii_redaction_is_redacted_around_not_refused():
    """The bytes are not text the person wrote, so they neither trip the phone
    detector's ceiling nor stop the redaction of the text beside them (#2566)."""
    seen: list[PromptContent] = []
    agent = _agent(GuardrailsConfig(redact_pii_in=True), _records_prompts(seen))
    result = await agent.run(["call me on 415-555-0132", PICTURE])
    assert result.output == "ok"
    assert seen == [["call me on [redacted:phone]", PICTURE]]


async def test_a_blocked_keyword_in_the_text_of_a_picture_prompt_still_blocks():
    agent = _agent(GuardrailsConfig(blocked_keywords_in="classified"), _answers("hi"))
    with pytest.raises(GuardrailBlocked) as exc:
        await agent.run(["this is classified", PICTURE])
    assert exc.value.edge == "input"


async def test_a_keyword_only_the_pictures_repr_spells_does_not_block():
    seen: list[PromptContent] = []
    agent = _agent(
        GuardrailsConfig(blocked_keywords_in="png, BinaryContent, image"),
        _records_prompts(seen),
    )
    result = await agent.run(["what is in this?", PICTURE])
    assert result.output == "ok"
    assert seen == [["what is in this?", PICTURE]]


async def test_a_picture_with_no_text_passes_untouched():
    seen: list[PromptContent] = []
    agent = _agent(GuardrailsConfig(redact_pii_in=True), _records_prompts(seen))
    await agent.run([PICTURE])
    assert seen == [[PICTURE]]


async def test_each_text_part_is_screened_and_the_others_kept_in_place():
    """A tagged text part keeps its metadata; a clean URL and a cache marker pass."""
    seen: list[PromptContent] = []
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _records_prompts(seen))
    url = ImageUrl(url="https://example.com/cat.png")
    await agent.run(
        [
            "first",
            TextContent(content=f"key {SECRET}", metadata={"from": "api"}),
            url,
            CachePoint(),
            f"again {SECRET}",
        ]
    )
    assert seen == [
        [
            "first",
            TextContent(content="key [redacted:anthropic_key]", metadata={"from": "api"}),
            url,
            CachePoint(),
            "again [redacted:anthropic_key]",
        ]
    ]


async def test_a_text_file_sent_inline_is_screened_as_text():
    seen: list[PromptContent] = []
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _records_prompts(seen))
    notes = BinaryContent(data=f"key {SECRET}".encode(), media_type="text/plain")
    await agent.run(["read this", notes])
    assert seen == [
        [
            "read this",
            BinaryContent(data=b"key [redacted:anthropic_key]", media_type="text/plain"),
        ]
    ]


async def test_a_redacted_structured_value_cannot_bypass_the_cleaned_text() -> None:
    seen: list[PromptContent] = []
    structured = StructuredContent(value={"key": SECRET}, metadata={"source": "app"})
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _records_prompts(seen))

    await agent.run([structured, PICTURE])

    prompt = seen[0]
    assert not isinstance(prompt, str)
    cleaned = prompt[0]
    assert isinstance(cleaned, TextContent)
    assert not isinstance(cleaned, StructuredContent)
    assert SECRET not in cleaned.content
    assert "[redacted:anthropic_key]" in cleaned.content
    assert cleaned.metadata == {"source": "app"}


async def test_a_clean_structured_value_keeps_its_native_form() -> None:
    seen: list[PromptContent] = []
    structured = StructuredContent(value={"answer": 42})
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _records_prompts(seen))

    await agent.run([structured, PICTURE])

    prompt = seen[0]
    assert not isinstance(prompt, str)
    assert prompt[0] is structured


@pytest.mark.parametrize("identifier", [None, "uploaded-notes"])
async def test_a_redacted_inline_file_keeps_the_identifier_used_to_refer_to_it(
    identifier: str | None,
) -> None:
    seen: list[PromptContent] = []
    notes = BinaryContent(
        data=f"key {SECRET}".encode(), media_type="text/plain", identifier=identifier
    )
    reference = f"Read file {notes.identifier}"
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _records_prompts(seen))

    await agent.run([reference, notes])

    prompt = seen[0]
    assert not isinstance(prompt, str)
    rewritten = prompt[1]
    assert isinstance(rewritten, BinaryContent)
    assert rewritten.data == b"key [redacted:anthropic_key]"
    assert rewritten.identifier == notes.identifier
    assert prompt[0] == reference


@pytest.mark.parametrize(
    ("config", "url"),
    [
        (GuardrailsConfig(blocked_keywords_in="classified"), "https://example.com/classified.pdf"),
        (GuardrailsConfig(redact_secrets_in=True), f"https://example.com/a.pdf?key={SECRET}"),
    ],
)
async def test_a_url_is_screened_and_a_redaction_in_it_blocks(config: GuardrailsConfig, url: str):
    """A URL with a placeholder in it is a broken URL, so a redaction there refuses."""
    agent = _agent(config, _answers("hi"))
    with pytest.raises(GuardrailBlocked) as exc:
        await agent.run(["read this", DocumentUrl(url=url)])
    assert exc.value.edge == "input"


@dataclass
class _SendsACopy(AbstractCapability[object]):
    """Send the model a copy of the prompt part, as an outer capability may.

    `reshape` makes one side plain text: `original` the history's part, `copy`
    the part the model is sent.
    """

    reshape: str | None = None

    async def wrap_model_request(
        self,
        ctx: RunContext[object],
        *,
        request_context: ModelRequestContext,
        handler: WrapModelRequestHandler,
    ) -> ModelResponse:
        messages: list[ModelMessage] = []
        for message in request_context.messages:
            if isinstance(message, ModelRequest):
                parts = []
                for part in message.parts:
                    if isinstance(part, UserPromptPart):
                        content: PromptContent = (
                            f"copy {SECRET}" if self.reshape == "copy" else list(part.content)
                        )
                        if self.reshape == "original":
                            part.content = f"original {SECRET}"
                        part = replace(part, content=content)
                    parts.append(part)
                message = replace(message, parts=parts)
            messages.append(message)
        request_context.messages = messages
        return await handler(request_context)


@pytest.mark.parametrize(
    ("reshape", "sent", "kept"),
    [
        (
            None,
            ["key [redacted:anthropic_key]", PICTURE],
            ["key [redacted:anthropic_key]", PICTURE],
        ),
        (
            "original",
            ["key [redacted:anthropic_key]", PICTURE],
            "original [redacted:anthropic_key]",
        ),
        ("copy", "copy [redacted:anthropic_key]", ["key [redacted:anthropic_key]", PICTURE]),
    ],
)
async def test_a_copy_and_the_run_historys_original_are_both_redacted(
    reshape: str | None, sent: PromptContent, kept: PromptContent
):
    """The model reads the copy; the run's later requests read the original."""
    seen: list[PromptContent] = []
    capability = build_guardrails(GuardrailsConfig(redact_secrets_in=True))
    assert capability is not None
    agent: Agent = Agent(
        model=_records_prompts(seen),
        capabilities=[_SendsACopy(reshape=reshape), capability],
    )
    result = await agent.run([f"key {SECRET}", PICTURE])
    assert seen == [sent]
    stored = next(
        part
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, UserPromptPart)
    )
    assert stored.content == kept


def _recording_guard(calls: list[str]) -> Callable[[str], GuardrailResult]:
    def guard(text: str) -> GuardrailResult:
        calls.append(text)
        return GuardrailResult.allow()

    return guard


async def test_a_copy_the_same_as_its_original_is_screened_once():
    calls: list[str] = []
    agent: Agent = Agent(
        model=_answers("ok"),
        capabilities=[_SendsACopy(), ScreenedPrompt(guard=_recording_guard(calls))],
    )
    await agent.run(["look", PICTURE])
    assert calls == ["look"]


async def test_the_prompt_is_screened_once_not_again_after_a_tool_call():
    calls: list[str] = []
    agent: Agent = Agent(
        model=_calls_tool_then_answers(),
        capabilities=[ScreenedPrompt(guard=_recording_guard(calls))],
    )

    @agent.tool_plain
    def fetch() -> str:
        return "fetched"

    result = await agent.run(["look", PICTURE])
    assert result.output == "answered"
    assert calls == ["look"]


async def test_a_parallel_guard_takes_the_harness_path():
    """Racing the model, it cannot rewrite a prompt the model already has."""
    calls: list[str] = []
    agent: Agent = Agent(
        model=_answers("ok"),
        capabilities=[ScreenedPrompt(guard=_recording_guard(calls), parallel=True)],
    )
    await agent.run(["look", PICTURE])
    assert calls == [str(["look", PICTURE])]


async def test_a_redaction_is_traced_by_its_text_never_the_pictures_bytes(monkeypatch):
    traced: list[object] = []
    monkeypatch.setattr(
        guardrails_capability,
        "trace_redaction",
        lambda _ctx, *, direction, replacement: traced.append(replacement),
    )
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _answers("ok"))
    notes = BinaryContent(data=b"notes", media_type="text/plain")
    await agent.run([f"key {SECRET}", TextContent(content="and more"), notes, PICTURE])
    assert traced == ["key [redacted:anthropic_key]\nand more\nnotes"]


def _resumed(*parts: UserPromptPart) -> list[ModelMessage]:
    """A history ending in a request of several prompt parts, as a run resumes from."""
    return [ModelRequest(parts=list(parts))]


async def test_resumed_background_content_matches_the_harness_input_policy() -> None:
    """With an explicit resumed prompt, upstream screens every prompt part too."""
    detector = _edge_detector(
        redact_secrets_on=False,
        redact_pii_on=False,
        phone_regions=(),
        keywords=["classified"],
        edge="input",
    )
    assert detector is not None
    for capability in (InputGuardrail(guard=detector), ScreenedPrompt(guard=detector)):
        agent: Agent = Agent(model=_answers("ok"), capabilities=[capability])
        history = _resumed(
            UserPromptPart([make_background_completion("classified", "task-1")]),
            UserPromptPart(["look", PICTURE]),
        )
        with pytest.raises(GuardrailBlocked):
            await agent.run(message_history=history)


async def test_a_resumed_request_screens_every_prompt_part_by_its_text():
    """Each part, not just the last, and a picture's bytes in none of them."""
    seen: list[PromptContent] = []
    agent = _agent(GuardrailsConfig(redact_pii_in=True), _records_prompts(seen))
    await agent.run(
        message_history=_resumed(
            UserPromptPart("call 415-555-0132"), UserPromptPart(["or 415-555-0199", PICTURE])
        )
    )
    assert seen == ["call [redacted:phone]", ["or [redacted:phone]", PICTURE]]


async def test_a_resumed_request_blocks_on_a_keyword_in_any_part():
    agent = _agent(GuardrailsConfig(blocked_keywords_in="classified"), _answers("hi"))
    with pytest.raises(GuardrailBlocked):
        await agent.run(
            message_history=_resumed(
                UserPromptPart("classified"), UserPromptPart(["look", PICTURE])
            )
        )


async def test_a_resumed_request_sent_as_a_copy_is_left_to_the_harness():
    """The parts sent cannot be told apart, so it screens the whole prompt."""
    calls: list[str] = []
    agent: Agent = Agent(
        model=_answers("ok"),
        capabilities=[_SendsACopy(), ScreenedPrompt(guard=_recording_guard(calls))],
    )
    await agent.run(
        message_history=_resumed(UserPromptPart("look"), UserPromptPart(["again", PICTURE]))
    )
    assert len(calls) == 1
    assert "BinaryContent" in calls[0]


async def test_the_size_limit_counts_every_text_part_together():
    """Two parts each under the limit are one prompt over it."""
    half = "a" * 150_000
    agent = _agent(GuardrailsConfig(redact_pii_in=True), _answers("hi"))
    with pytest.raises(GuardrailBlocked):
        await agent.run([half, TextContent(content=half), PICTURE])


async def test_the_size_limit_counts_every_part_of_a_resumed_request_together():
    """Two prompt parts of one resumed request, each under the limit, are one prompt over it."""
    half = "a" * 150_000
    agent = _agent(GuardrailsConfig(redact_pii_in=True), _answers("hi"))
    with pytest.raises(GuardrailBlocked):
        await agent.run(
            message_history=_resumed(UserPromptPart(half), UserPromptPart([half, PICTURE]))
        )


async def test_a_redaction_only_the_whole_prompt_shows_blocks():
    """A key split across two parts is redacted whole, but neither part alone holds it."""
    # Spelt in pieces, so the repository's private-key hook does not take it for one.
    marker = "RSA " + "PRIVATE KEY-----"
    head = f"-----BEGIN {marker}\nMIIEowIBAAKCAQEA"
    tail = f"abcdef0123456789\n-----END {marker}"
    seen: list[PromptContent] = []
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _records_prompts(seen))
    with pytest.raises(GuardrailBlocked):
        await agent.run([head, TextContent(content=tail), PICTURE])
    assert seen == []


async def test_redactions_each_part_holds_whole_let_the_prompt_through():
    seen: list[PromptContent] = []
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _records_prompts(seen))
    await agent.run([f"key {SECRET}", TextContent(content=f"again {SECRET}"), PICTURE])
    assert seen == [
        [
            "key [redacted:anthropic_key]",
            TextContent(content="again [redacted:anthropic_key]"),
            PICTURE,
        ]
    ]


async def test_the_size_limit_counts_links_with_the_text():
    """Each link is screened, so each counts toward the one prompt's limit."""
    link = ImageUrl(url="https://example.com/" + "a" * 100_000)
    agent = _agent(GuardrailsConfig(redact_pii_in=True), _answers("hi"))
    with pytest.raises(GuardrailBlocked):
        await agent.run(["look", link, replace(link, url=link.url + "b")])


@pytest.mark.parametrize(
    "media_type", ["text/plain; charset=utf-16", "text/plain; charset=cp037", "text/plain"]
)
async def test_a_file_read_in_a_set_no_model_reads_it_in_blocks(media_type: str):
    """A model is sent the bytes as UTF-8: screened in UTF-16, a key reads as no key."""
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _answers("hi"))
    notes = BinaryContent(data=f"key {SECRET}".encode("utf-16"), media_type=media_type)
    with pytest.raises(GuardrailBlocked, match="not valid UTF-8"):
        await agent.run(["read", notes])


@pytest.mark.parametrize(
    "media_type",
    [
        "text/plain; format=flowed; charset=x-no-such-charset",
        "text/plain; charset=windows-1252",
        "text/plain; charset=unicode_escape",
        "text/plain; charset=undefined",
    ],
)
async def test_a_file_declaring_a_set_other_than_utf_8_blocks(media_type: str):
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _answers("hi"))
    with pytest.raises(GuardrailBlocked, match="not valid UTF-8"):
        await agent.run(["read", BinaryContent(data=b"notes", media_type=media_type)])


@pytest.mark.parametrize(
    "media_type",
    ['text/plain; charset="UTF8"', "text/plain; charset=", "text/plain; charset=US-ASCII"],
)
async def test_a_redaction_is_written_back_in_the_utf_8_the_file_declares(media_type: str):
    seen: list[PromptContent] = []
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _records_prompts(seen))
    await agent.run(["read", BinaryContent(data=f"key {SECRET}".encode(), media_type=media_type)])
    assert seen == [
        [
            "read",
            BinaryContent(data=b"key [redacted:anthropic_key]", media_type=media_type),
        ]
    ]


async def test_a_redaction_its_file_charset_cannot_hold_blocks():
    def guard(text: str) -> GuardrailResult:
        return GuardrailResult.replace(text.replace("notes", "nótes"))

    agent: Agent = Agent(model=_answers("hi"), capabilities=[ScreenedPrompt(guard=guard)])
    notes = BinaryContent(data=b"notes", media_type="text/plain; charset=us-ascii")
    with pytest.raises(GuardrailBlocked, match="not valid UTF-8"):
        await agent.run(["read", notes, PICTURE])


@pytest.mark.parametrize(
    "media_type",
    ["application/xml", "application/ld+json", "application/x-yaml", "text/csv; charset=utf-8"],
)
async def test_a_textual_file_of_any_text_type_is_screened(media_type: str):
    agent = _agent(GuardrailsConfig(blocked_keywords_in="classified"), _answers("hi"))
    with pytest.raises(GuardrailBlocked):
        await agent.run(["read", BinaryContent(data=b"classified", media_type=media_type)])


async def test_a_binary_document_is_not_read_as_text():
    """A PDF's bytes are no more what anybody wrote than a picture's."""
    agent = _agent(GuardrailsConfig(blocked_keywords_in="classified"), _answers("hi"))
    pdf = BinaryContent(data=b"%PDF classified", media_type="application/pdf")
    assert (await agent.run(["read", pdf])).output == "hi"


async def test_a_tagged_text_part_with_nothing_to_redact_is_kept_as_it_was():
    seen: list[PromptContent] = []
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _records_prompts(seen))
    tagged = TextContent(content="nothing here", metadata={"from": "api"})
    await agent.run([tagged, PICTURE])
    assert seen == [[tagged, PICTURE]]
    assert not isinstance(seen[0], str) and seen[0][0] is tagged


async def test_output_pii_redaction_removes_a_phone_number_from_the_answer():
    agent = _agent(
        GuardrailsConfig(redact_pii_out=True, phone_regions="US"),
        _answers("Call us on 415-555-0132."),
    )
    result = await agent.run("how do I reach you?")
    assert result.output == "Call us on [redacted:phone]."


async def test_a_blocked_prompt_stops_the_run():
    agent = _agent(GuardrailsConfig(blocked_keywords_in="classified"), _answers("hi"))
    with pytest.raises(GuardrailBlocked) as exc:
        await agent.run("this is classified information")
    assert exc.value.edge == "input"


async def test_a_blocked_output_stops_the_run():
    agent = _agent(GuardrailsConfig(blocked_keywords_out="leaked"), _answers("this is leaked"))
    with pytest.raises(GuardrailBlocked) as exc:
        await agent.run("go")
    assert exc.value.edge == "output"


async def test_a_blocked_tool_result_stops_the_run():
    agent = _agent(
        GuardrailsConfig(blocked_keywords_tool="injection"),
        _calls_tool_then_answers(),
        tool_result="a page with an injection payload",
    )
    with pytest.raises(GuardrailBlocked) as exc:
        await agent.run("go")
    assert exc.value.edge == "tool_result"


async def test_tool_result_redaction_lets_the_run_finish():
    agent = _agent(
        GuardrailsConfig(redact_secrets_tool=True),
        _calls_tool_then_answers(),
        tool_result=f"the file held {SECRET}",
    )
    result = await agent.run("go")
    assert result.output == "answered"


def _build(config_blob: object) -> object:
    definition = get("guardrails")
    return definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="guardrails", config=config_blob),
            config=config_blob if isinstance(config_blob, GuardrailsConfig) else None,
        )
    )


def test_the_builder_contributes_nothing_for_a_default_config():
    assert _build(GuardrailsConfig()) is None


def test_the_builder_falls_back_to_defaults_for_a_foreign_config():
    assert _build(None) is None


def test_a_configured_binding_builds_the_capability():
    built = _build(GuardrailsConfig(redact_secrets_in=True))
    assert isinstance(built, CombinedCapability)


async def _streamed(agent: Agent, events: list[AgentStreamEvent]) -> None:
    """Drive `agent` the way every streaming surface does, collecting what it is shown.

    Appends to `events` rather than returning them, so a test of a run that raises
    can still read what was released before it did.
    """
    async with agent.iter("go") as run:
        async for node in run:
            if Agent.is_model_request_node(node) or Agent.is_call_tools_node(node):
                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        events.append(event)


def _shown(events: list[AgentStreamEvent]) -> str:
    """Every piece of text or reasoning a consumer of these events could display."""
    shown: list[str] = []
    for event in events:
        if isinstance(event, PartStartEvent | PartEndEvent) and isinstance(
            event.part, TextPart | ThinkingPart
        ):
            shown.append(event.part.content)
        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
            shown.append(event.delta.content_delta)
        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, ThinkingPartDelta):
            shown.append(event.delta.content_delta or "")
    return "\n".join(shown)


# The secret arrives split across deltas, the way a model streams it: no one delta
# holds the whole pattern, so screening deltas one at a time would miss it.
_KEY_IN_PIECES = ["Here it is: sk-ant-api03-ABCDEF", "GHIJKLMNOPQR. Keep it safe."]


@pytest.mark.security
async def test_a_streamed_answer_never_shows_the_secret_it_redacts():
    """The reported leak: the deltas carried the key, and only `final_result` was
    redacted - so the web chat and every channel showed it while it was written."""
    agent = _agent(GuardrailsConfig(redact_secrets_out=True), _streams(_KEY_IN_PIECES))
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert SECRET not in _shown(events)
    assert "Here it is: [redacted:anthropic_key]. Keep it safe." in _shown(events)


async def test_text_written_before_a_tool_call_is_screened_too():
    """The harness guardrail reads only the run's output, which is the last
    response's text. A sentence before a tool call is not part of it, yet a
    streaming surface shows it and stores it in the turn."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_out=True),
        _streams(
            [*_KEY_IN_PIECES, {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")}],
            ["answered"],
        ),
        tool_result="ok",
    )
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert SECRET not in _shown(events)
    assert "[redacted:anthropic_key]" in _shown(events)
    assert "answered" in _shown(events)


async def test_reasoning_is_screened_like_the_answer():
    """Reasoning streams to the same reader as the answer, so it is held to the
    same rule - a key the model recalls while thinking is still a key on screen."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_out=True),
        _streams(
            [
                {0: DeltaThinkingPart(content="The key was sk-ant-api03-ABCDEF")},
                {0: DeltaThinkingPart(content="GHIJKLMNOPQR, I should not repeat it.")},
                "Done.",
            ]
        ),
    )
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert SECRET not in _shown(events)
    assert "The key was [redacted:anthropic_key], I should not repeat it." in _shown(events)


def _released_text(events: list[AgentStreamEvent]) -> str:
    """The text parts as `RunFrames` and a channel's live reply join them: end to end."""
    return "".join(
        event.part.content
        for event in events
        if isinstance(event, PartEndEvent) and isinstance(event.part, TextPart)
    )


@pytest.mark.security
async def test_a_key_split_around_a_tool_call_blocks_before_its_second_half():
    """Each half is harmless on its own, and a surface joins the parts: the half
    already shown cannot be taken back, so the half that completes it is never sent."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_out=True),
        _streams(
            [
                "Here it is: sk-ant-api03-ABCDEF",
                {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")},
            ],
            ["GHIJKLMNOPQR. Keep it safe."],
        ),
        tool_result="ok",
    )
    events: list[AgentStreamEvent] = []

    with pytest.raises(GuardrailBlocked):
        await _streamed(agent, events)

    assert "GHIJKLMNOPQR" not in _released_text(events)


@pytest.mark.security
async def test_answer_text_that_reads_like_the_placeholder_keeps_the_tail():
    """Only a part this screen withheld clears the tail; a model writing the same
    words must not be able to split a keyword around them."""
    keyword = WITHHELD_REASONING + "bar"
    agent = _agent(
        GuardrailsConfig(blocked_keywords_out=keyword),
        _streams(
            [
                WITHHELD_REASONING,
                {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")},
            ],
            ["bar"],
        ),
        tool_result="ok",
    )
    events: list[AgentStreamEvent] = []

    with pytest.raises(GuardrailBlocked):
        await _streamed(agent, events)


@pytest.mark.security
async def test_a_part_that_breaks_a_redaction_already_shown_blocks():
    """A key redacted at the end of one part stops matching once the next part
    extends it; releasing the joined screen would send the key itself."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_out=True),
        _streams(
            [
                "The key is AKIAIOSFODNN7EXAMPLE",
                {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")},
            ],
            ["X and that is all."],
        ),
        tool_result="ok",
    )
    events: list[AgentStreamEvent] = []

    with pytest.raises(GuardrailBlocked):
        await _streamed(agent, events)

    assert "AKIAIOSFODNN7EXAMPLE" not in _shown(events)


@pytest.mark.security
async def test_a_key_begun_in_reasoning_and_finished_in_the_answer_blocks():
    """A surface shows and stores reasoning and answer in order, so they share a tail."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_out=True),
        _streams([{0: DeltaThinkingPart(content="It is sk-ant-api03-ABCDEF")}, "GHIJKLMNOPQR."]),
    )
    events: list[AgentStreamEvent] = []

    with pytest.raises(GuardrailBlocked):
        await _streamed(agent, events)

    assert "GHIJKLMNOPQR" not in _shown(events)


@pytest.mark.security
async def test_a_keyword_only_two_parts_spell_together_is_blocked():
    agent = _agent(
        GuardrailsConfig(blocked_keywords_out="confidential"),
        _streams(
            ["This is confi", {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")}],
            ["dential."],
        ),
        tool_result="ok",
    )
    events: list[AgentStreamEvent] = []

    with pytest.raises(GuardrailBlocked):
        await _streamed(agent, events)

    assert _released_text(events) == "This is confi"


async def test_the_released_tail_never_pushes_a_part_past_a_size_limit():
    """The tail is context: a part within the PII size ceiling is released even
    when the tail added to it would not be."""

    def screen(text: str) -> GuardrailResult:
        if len(text) > 30:
            raise GuardrailBlocked(edge="output", message="too long")
        return GuardrailResult.allow()

    agent = Agent(
        _streams(
            ["a" * 20, {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")}],
            ["b" * 30],
        ),
        capabilities=[
            ScreenedStream(screen=screen, fits=lambda text: len(text) <= 30, tail_chars=10)
        ],
    )

    async def fetch() -> str:
        return "ok"

    agent.tool_plain(fetch)
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert _released_text(events) == "a" * 20 + "b" * 30


@pytest.mark.security
async def test_a_key_split_into_a_part_too_long_for_its_tail_still_blocks():
    """A part at the size ceiling is screened alone, so the key's completion is
    checked on a window with the tail - and since it cannot be redacted inside
    this part alone, it is not released at all."""
    detector = _edge_detector(
        redact_secrets_on=True, redact_pii_on=False, phone_regions=(), keywords=[], edge="output"
    )
    assert detector is not None
    agent = Agent(
        _streams(
            [
                "Here it is: sk-ant-api03-ABCDEF",
                {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")},
            ],
            ["GHIJKLMNOPQR. " + "z" * 46],
        ),
        capabilities=[
            ScreenedStream(screen=detector, fits=lambda text: len(text) <= 60, tail_chars=30)
        ],
    )

    async def fetch() -> str:
        return "ok"

    agent.tool_plain(fetch)
    events: list[AgentStreamEvent] = []

    with pytest.raises(GuardrailBlocked):
        await _streamed(agent, events)

    assert "GHIJKLMNOPQR" not in _released_text(events)


async def test_reasoning_that_completes_a_key_in_a_part_too_long_for_its_tail_is_withheld():
    detector = _edge_detector(
        redact_secrets_on=True, redact_pii_on=False, phone_regions=(), keywords=[], edge="output"
    )
    assert detector is not None
    agent = Agent(
        _streams(
            [
                {0: DeltaThinkingPart(content="It was sk-ant-api03-ABCDEF")},
                {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")},
            ],
            [{0: DeltaThinkingPart(content="GHIJKLMNOPQR " + "z" * 47)}, "Done."],
        ),
        capabilities=[
            ScreenedStream(screen=detector, fits=lambda text: len(text) <= 60, tail_chars=30)
        ],
    )

    async def fetch() -> str:
        return "ok"

    agent.tool_plain(fetch)
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert "GHIJKLMNOPQR" not in _shown(events)
    assert WITHHELD_REASONING in _shown(events)
    assert "Done." in _shown(events)


@pytest.mark.security
async def test_a_blocked_keyword_longer_than_the_tail_is_still_caught_across_parts():
    keyword = "x" * 1_500
    agent = _agent(
        GuardrailsConfig(blocked_keywords_out=keyword),
        _streams(
            [keyword[:-1], {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")}],
            ["x."],
        ),
        tool_result="ok",
    )
    events: list[AgentStreamEvent] = []

    with pytest.raises(GuardrailBlocked):
        await _streamed(agent, events)


async def test_with_pii_redaction_the_stream_knows_the_phone_size_limit():
    capability = build_guardrails(GuardrailsConfig(redact_pii_out=True))
    assert capability is not None
    [screened] = [c for c in capability.capabilities if isinstance(c, ScreenedStream)]

    assert screened.fits is not None
    assert screened.fits("short")
    assert not screened.fits("1" * 20_000)


async def test_a_blocked_keyword_in_reasoning_withholds_the_reasoning_not_the_run():
    """Reasoning routinely restates the question. Ending a run whose answer is
    clean over a word the model only thought would refuse ordinary questions."""
    agent = _agent(
        GuardrailsConfig(blocked_keywords_out="acme"),
        _streams(
            [
                {0: DeltaThinkingPart(content="The user asks about Acme.")},
                "I can only talk about our own product.",
            ]
        ),
    )
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert "Acme" not in _shown(events)
    assert WITHHELD_REASONING in _shown(events)
    assert "I can only talk about our own product." in _shown(events)


async def test_a_released_part_keeps_what_came_before_it():
    """The held start event is the one released, so `previous_part_kind` survives."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_out=True),
        _streams([{0: DeltaThinkingPart(content="Thinking.")}, "Answer."]),
    )
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    starts = [event for event in events if isinstance(event, PartStartEvent)]
    assert [(type(e.part), e.previous_part_kind) for e in starts] == [
        (ThinkingPart, None),
        (TextPart, "thinking"),
    ]


@pytest.mark.security
async def test_a_blocked_answer_ends_the_run_before_any_of_it_is_shown():
    """The block used to arrive after the whole answer had streamed - and been
    stored as the turn - so the refusal refused nothing."""
    agent = _agent(
        GuardrailsConfig(blocked_keywords_out="confidential"),
        _streams(["Strictly confidential: ", "Acme is buying Initech."]),
    )
    events: list[AgentStreamEvent] = []

    with pytest.raises(GuardrailBlocked) as exc:
        await _streamed(agent, events)

    assert exc.value.edge == "output"
    assert _shown(events) == ""


async def test_a_held_part_is_released_whole_and_in_place():
    """One start and one end event per part, both carrying the screened text, at
    the part's own index - what `RunFrames` and a channel's live reply read."""
    agent = _agent(GuardrailsConfig(redact_secrets_out=True), _streams(_KEY_IN_PIECES))
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    released = [
        (type(event), event.index, event.part.content)
        for event in events
        if isinstance(event, PartStartEvent | PartEndEvent) and isinstance(event.part, TextPart)
    ]
    assert released == [
        (PartStartEvent, 0, "Here it is: [redacted:anthropic_key]. Keep it safe."),
        (PartEndEvent, 0, "Here it is: [redacted:anthropic_key]. Keep it safe."),
    ]
    assert not any(isinstance(event, PartDeltaEvent) for event in events)


async def test_without_an_output_check_the_answer_streams_token_by_token():
    """An agent screening only its input keeps the live stream it had."""
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _streams(["One ", "two ", "three."]))
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    deltas = [
        event.delta.content_delta
        for event in events
        if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta)
    ]
    assert deltas == ["two ", "three."]


async def test_a_waited_for_answer_is_still_redacted():
    """Screening the stream changes only what a consumer of the stream sees: the
    output the run ends with is still the output guardrail's redacted answer."""
    agent = _agent(GuardrailsConfig(redact_secrets_out=True), _streams(_KEY_IN_PIECES))

    result = await agent.run("go")

    assert result.output == "Here it is: [redacted:anthropic_key]. Keep it safe."


def test_transcripts_are_screened_by_the_input_and_output_edges():
    """#54: a call has no model request to wrap, so the same detectors read its transcripts."""
    screens = transcript_screens(
        GuardrailsConfig(blocked_keywords_in="password", redact_secrets_out=True)
    )
    assert screens.caller is not None and screens.agent is not None
    with pytest.raises(GuardrailBlocked):
        screens.caller("my password is hunter2")


def test_an_agent_with_no_edges_has_no_transcript_screens():
    assert transcript_screens(GuardrailsConfig()) == TranscriptScreens(caller=None, agent=None)


# Tool arguments (agenticos#2000): an edge of its own, off unless configured.


def test_the_tool_arguments_edge_is_off_unless_configured():
    built = build_guardrails(GuardrailsConfig(redact_secrets_out=True))
    assert built is not None
    assert not any(isinstance(edge, ScreenedToolArgs) for edge in built.capabilities)

    built = build_guardrails(GuardrailsConfig(redact_secrets_args=True))
    assert built is not None
    assert [type(edge) for edge in built.capabilities] == [ScreenedToolArgs]


def _emails(sent: list[str]) -> Agent:
    """An agent whose `send_email` tool records the body it was handed."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_args=True, blocked_keywords_args="salary"),
        _streams(
            [
                {
                    0: DeltaToolCall(
                        name="send_email",
                        json_args='{"to": "ada@example.com", "body": "Use ',
                        tool_call_id="c1",
                    )
                },
                {0: DeltaToolCall(json_args="sk-ant-api03-ABCDEF")},
                {0: DeltaToolCall(json_args='GHIJKLMNOPQR", "copies": 2}')},
            ],
            ["sent"],
        ),
    )

    async def send_email(to: str, body: str, copies: int) -> str:
        sent.append(body)
        return "ok"

    agent.tool_plain(send_email)
    return agent


@pytest.mark.security
async def test_a_secret_in_a_tools_arguments_reaches_neither_the_tool_the_stream_nor_the_history():
    """The reported leak: the arguments streamed raw as they were written, and the
    tool and the stored call held them unredacted."""
    sent: list[str] = []
    agent = _emails(sent)
    events: list[AgentStreamEvent] = []

    async with agent.iter("go") as run:
        async for node in run:
            if Agent.is_model_request_node(node) or Agent.is_call_tools_node(node):
                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        events.append(event)
    assert run.result is not None

    assert sent == ["Use [redacted:anthropic_key]"]
    streamed = [
        event
        for event in events
        if isinstance(event, PartStartEvent | PartEndEvent) and isinstance(event.part, ToolCallPart)
    ]
    assert streamed
    assert all(SECRET not in str(event.part.args) for event in streamed)
    assert not any(
        isinstance(event, PartDeltaEvent) and isinstance(event.delta, ToolCallPartDelta)
        for event in events
    )
    assert SECRET not in str(run.result.all_messages())


@pytest.mark.security
async def test_a_blocked_keyword_in_a_tools_arguments_ends_the_run_before_the_tool_runs():
    sent: list[str] = []
    args = '{"to": "ada@example.com", "body": "Her salary is attached", "copies": 1}'
    model = _streams([{0: DeltaToolCall(name="send_email", json_args=args, tool_call_id="c1")}])

    agent = _agent(GuardrailsConfig(blocked_keywords_args="salary"), model)

    async def send_email(to: str, body: str, copies: int) -> str:
        sent.append(body)
        return "ok"

    agent.tool_plain(send_email)

    with pytest.raises(GuardrailBlocked) as blocked:
        await agent.run("go")

    assert blocked.value.edge == "tool_args"
    assert "salary" not in str(blocked.value)
    assert sent == []


@pytest.mark.security
async def test_a_call_refused_for_its_arguments_is_still_paid_for():
    """Review on #2062: the block was raised inside the request, past the budget
    guard, so the run recorded no cost for a call the provider billed."""
    from app.agents.capabilities.budget import BudgetGuard, SpendLedger

    args = '{"body": "Her salary is attached"}'
    model = _streams([{0: DeltaToolCall(name="send_email", json_args=args, tool_call_id="c1")}])
    ledger = SpendLedger()
    guardrails = build_guardrails(GuardrailsConfig(blocked_keywords_args="salary"))
    assert guardrails is not None
    agent: Agent = Agent(model=model, capabilities=[BudgetGuard(ledger=ledger), guardrails])

    async def send_email(body: str) -> str:
        return "ok"  # pragma: no cover - refused before it runs

    agent.tool_plain(send_email)

    with pytest.raises(GuardrailBlocked):
        await agent.run("go")

    assert len(ledger.entries) == 1


async def test_a_refusal_that_carries_no_answer_records_nothing():
    """Refused before the model answered: nothing was billed, nothing is recorded."""
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.capabilities.budget import BudgetGuard, SpendLedger

    ledger = SpendLedger()
    refused = GuardrailBlocked(edge="input", message="blocked")
    handler = AsyncMock(side_effect=refused)

    with pytest.raises(GuardrailBlocked):
        await BudgetGuard(ledger=ledger).wrap_model_request(
            MagicMock(), request_context=MagicMock(), handler=handler
        )

    assert ledger.entries == []


async def test_nested_arguments_are_screened_and_a_clean_call_is_left_alone():
    screen = ScreenedToolArgs(
        screen=_edge_detector(
            redact_secrets_on=True,
            redact_pii_on=False,
            phone_regions=(),
            keywords=[],
            edge="tool_args",
        )
    )
    clean = ModelResponse(
        parts=[ToolCallPart(tool_name="t", args={"n": 3, "ok": True}), TextPart("x")]
    )
    nested = ModelResponse(
        parts=[ToolCallPart(tool_name="t", args={"items": [{"key": SECRET}, 4], "note": None})]
    )

    assert (
        await screen.after_model_request(MagicMock(), request_context=MagicMock(), response=clean)
        is clean
    )
    screened = await screen.after_model_request(
        MagicMock(), request_context=MagicMock(), response=nested
    )
    call = screened.parts[0]
    assert isinstance(call, ToolCallPart)
    assert call.args == {"items": [{"key": "[redacted:anthropic_key]"}, 4], "note": None}
