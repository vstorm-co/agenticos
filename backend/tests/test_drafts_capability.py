"""The drafts capability: a card validated by the tool, offered only where it shows."""

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage

from app.agents.capabilities.drafts import Drafts, DraftsToolset
from app.agents.capabilities.drafts._spec import (
    DRAFTED,
    WRITE_DRAFT,
    DraftCard,
    DraftField,
    parse_draft_card,
)
from app.agents.capabilities.drafts._toolset import DraftFieldInput, DraftVersionInput
from app.agents.deps import AgentDeps

_drafts = DraftsToolset()


def _tool_ctx(
    *, retry: int = 0, max_retries: int = 1, deps: AgentDeps | None = None
) -> RunContext[AgentDeps]:
    return RunContext(
        deps=deps or AgentDeps(),
        model=TestModel(),
        usage=RunUsage(),
        retry=retry,
        max_retries=max_retries,
    )


def _version(label: str | None = None, text: str = "Hello") -> DraftVersionInput:
    return DraftVersionInput(label=label, fields=[DraftFieldInput(text=text)])


class TestWriteDraft:
    def test_a_draft_comes_back_as_drafted_and_names_its_title(self):
        result = _drafts.write_draft(
            _tool_ctx(),
            title="Reply to Marta",
            kind="Email",
            versions=[
                DraftVersionInput(
                    fields=[
                        DraftFieldInput(name="Subject", text="Re: Q4 deck"),
                        DraftFieldInput(name="Body", text="Thanks, Marta."),
                    ]
                )
            ],
        )

        assert result.startswith(DRAFTED)
        assert "'Reply to Marta'" in result
        assert "do not write it out again" in result

    def test_two_versions_without_labels_go_back_for_a_retry(self):
        with pytest.raises(ModelRetry, match="label"):
            _drafts.write_draft(
                _tool_ctx(), title="t", kind="Post", versions=[_version(), _version()]
            )

    def test_two_versions_with_the_same_label_go_back_for_a_retry(self):
        with pytest.raises(ModelRetry):
            _drafts.write_draft(
                _tool_ctx(),
                title="t",
                kind="Post",
                versions=[_version("Short"), _version("short")],
            )

    def test_on_the_last_attempt_the_refusal_is_the_result(self):
        result = _drafts.write_draft(
            _tool_ctx(retry=1, max_retries=1),
            title="t",
            kind="Post",
            versions=[_version(), _version()],
        )

        assert not result.startswith(DRAFTED)

    def test_a_whitespace_only_field_is_not_a_draft(self):
        with pytest.raises(ValidationError):
            DraftField(text="  \n ")
        with pytest.raises(ModelRetry):
            _drafts.write_draft(
                _tool_ctx(), title="t", kind="Post", versions=[_version(text="  \n ")]
            )

    def test_a_blank_title_or_kind_goes_back_for_a_retry(self):
        with pytest.raises(ModelRetry, match="title"):
            _drafts.write_draft(_tool_ctx(), title="  ", kind="Post", versions=[_version()])
        with pytest.raises(ModelRetry, match="kind"):
            _drafts.write_draft(_tool_ctx(), title="t", kind="\n", versions=[_version()])

    def test_a_stored_draft_with_a_blank_title_still_parses(self):
        card = parse_draft_card(
            {"title": " ", "kind": "Post", "versions": [{"fields": [{"text": "Hi"}]}]}
        )

        assert card is not None

    def test_a_field_error_names_its_full_path(self):
        version = DraftVersionInput(fields=[DraftFieldInput(text="ok"), DraftFieldInput(text=" ")])

        with pytest.raises(ModelRetry, match=r"versions\.0\.fields\.1\.text"):
            _drafts.write_draft(_tool_ctx(), title="t", kind="Post", versions=[version])

    def test_the_tool_tells_the_model_to_write_plain_text_and_not_repeat_it(self):
        description = _drafts.tools[WRITE_DRAFT].tool_def.description or ""

        assert "plain text" in description.lower()
        assert "do not repeat" in description.lower()

    def test_the_tool_asks_for_a_bracketed_placeholder_and_keeps_given_brackets(self):
        description = _drafts.tools[WRITE_DRAFT].tool_def.description or ""

        assert "[Your Name]" in description
        assert "square brackets" in description
        assert "[WIP]" in description


class TestTheInstruction:
    def _instruction(self, deps: AgentDeps) -> str:
        return Drafts().get_instructions()(_tool_ctx(deps=deps))

    def test_where_the_card_shows_the_answer_is_told_not_to_repeat_it(self):
        text = self._instruction(AgentDeps(shows_drafts=True))

        assert WRITE_DRAFT in text
        assert "never writes the draft out again" in text

    def test_the_instruction_asks_for_placeholders_in_square_brackets(self):
        text = self._instruction(AgentDeps(shows_drafts=True))

        assert "square brackets" in text
        assert "[Your Name]" in text

    def test_where_no_card_shows_there_is_no_instruction(self):
        assert self._instruction(AgentDeps(shows_drafts=False)) == ""

    def test_a_delegated_run_gets_no_instruction(self):
        assert self._instruction(AgentDeps(shows_drafts=True, delegated=True)) == ""


class TestTheFormat:
    def test_six_versions_are_more_than_a_card_holds(self):
        versions = [{"label": f"v{n}", "fields": [{"text": "x"}]} for n in range(6)]
        with pytest.raises(ValidationError):
            DraftCard.model_validate({"title": "t", "kind": "Post", "versions": versions})

    def test_a_format_outside_the_pattern_is_refused(self):
        with pytest.raises(ValidationError):
            DraftField(text="x", format="Python Script")

    def test_a_card_that_fits_parses(self):
        card = parse_draft_card(
            {"title": "t", "kind": "Post", "versions": [{"fields": [{"text": "x"}]}]}
        )

        assert card is not None
        assert card.versions[0].fields[0].format == "text"

    def test_two_distinctly_labelled_versions_parse(self):
        card = parse_draft_card(
            {
                "title": "t",
                "kind": "Post",
                "versions": [
                    {"label": "Short", "fields": [{"text": "x"}]},
                    {"label": "Long", "fields": [{"text": "y"}]},
                ],
            }
        )

        assert card is not None
        assert [v.label for v in card.versions] == ["Short", "Long"]

    def test_a_stored_shape_that_does_not_parse_is_none(self):
        assert parse_draft_card({"title": "x"}) is None
        assert parse_draft_card(None) is None
        assert parse_draft_card({"title": "x", "kind": "Email", "versions": "nope"}) is None


class TestWhereTheCardShows:
    async def _offered(self, deps: AgentDeps) -> bool:
        tools = await Drafts().get_toolset().get_tools(_tool_ctx(deps=deps))
        return WRITE_DRAFT in tools

    @pytest.mark.anyio
    async def test_the_tool_is_not_offered_where_no_card_can_show(self):
        assert not await self._offered(AgentDeps())

    @pytest.mark.anyio
    async def test_the_tool_is_offered_in_the_web_chat(self):
        assert await self._offered(AgentDeps(shows_drafts=True))

    def test_a_delegate_is_never_offered_a_draft(self):
        assert AgentDeps(shows_drafts=True).clone_for_subagent().shows_drafts is False

    @pytest.mark.anyio
    async def test_a_delegated_run_is_not_offered_it_even_with_the_flag(self):
        assert not await self._offered(AgentDeps(shows_drafts=True, delegated=True))

    def test_the_toolset_is_built_once(self):
        capability = Drafts()

        assert capability.get_toolset() is capability.get_toolset()


@pytest.mark.anyio
async def test_a_card_the_limits_refuse_twice_does_not_end_the_run():
    too_many = {
        "title": "t",
        "kind": "Post",
        "versions": [{"label": f"v{n}", "fields": [{"text": "x"}]} for n in range(6)],
    }

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returns = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if len(returns) < 2 and len(messages) < 5:
            return ModelResponse(parts=[ToolCallPart(WRITE_DRAFT, too_many)])
        return ModelResponse(parts=[TextPart("Sorry, that was too many.")])

    agent = Agent(FunctionModel(model), toolsets=[DraftsToolset()], deps_type=AgentDeps)

    result = await agent.run("draft", deps=AgentDeps())

    assert result.output == "Sorry, that was too many."
    returned = [
        part.content
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert returned
    assert not str(returned[-1]).startswith(DRAFTED)
