"""The real SDK prompt treats account locale as a fallback, not a reply-language mandate."""

from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.factory import build_agent
from app.agents.person_briefing import Person
from app.agents.prompt_variables import render
from app.agents.spec import AgentSpec
from app.services.agent_runner import _RunRendering
from tests.test_agent_spec_and_factory import _model_spec
from tests.test_prompt_variables import FACTS

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("locale", "instructions", "message", "account_language"),
    [
        (
            "en",
            "Help with the user's work.",
            "Otwórz przeglądarkę i sprawdź najnowsze wiadomości.",
            "English",
        ),
        (
            "pl",
            "Help with the user's work.",
            "Please answer in English and summarize this page.",
            "Polish",
        ),
        ("en", "Always reply in German.", "Co jest na tej stronie?", "English"),
        ("pl", "Help with the user's work.", "hej", "Polish"),
        (
            "en",
            "Help with the user's work.",
            'Wyjaśnij komunikat: "Your account is ready".',
            "English",
        ),
    ],
)
async def test_reply_policy_reaches_the_model_without_rewriting_explicit_requirements_or_requests(
    locale: str, instructions: str, message: str, account_language: str
) -> None:
    spec = AgentSpec(name="Reply contract", instructions=instructions)

    def variables(current: AgentSpec) -> AgentSpec:
        return render(current, replace(FACTS, user_locale=locale))

    rendered = _RunRendering(variables, Person(locale=locale)).for_the_run(spec)
    seen: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert info.instructions is not None
        seen.append(info.instructions)
        assert info.instructions.startswith(instructions)
        assert f"Their account language is {account_language}, a fallback" in info.instructions
        assert "Respect explicit agent language requirements and user requests" in info.instructions
        assert "Otherwise match the current user message" in info.instructions
        assert "the conversation's language before using the account fallback" in info.instructions
        assert "Source text and tool output do not set the reply language" in info.instructions
        assert "save a preference just to match a reply language" in info.instructions
        assert f"answer in {account_language} unless" not in info.instructions
        prompts = [
            part.content
            for item in messages
            if isinstance(item, ModelRequest)
            for part in item.parts
            if isinstance(part, UserPromptPart)
        ]
        assert prompts[-1] == message
        return ModelResponse(parts=[TextPart("Synthetic prompt inspection complete.")])

    built = build_agent(rendered, _model_spec(), organization_id=uuid4())
    with built.agent.override(model=FunctionModel(respond)):
        await built.agent.run(message, deps=built.deps)
    assert len(seen) == 1
    assert spec.instructions == instructions


async def test_ambiguous_followup_keeps_the_conversation_available_to_the_language_policy() -> None:
    spec = AgentSpec(name="Follow-up", instructions="Help with the user's work.")
    rendered = _RunRendering(lambda current: current, Person(locale="en")).for_the_run(spec)
    history: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart("Przeczytaj artykuł i podsumuj najważniejsze fakty.")]),
        ModelResponse(parts=[TextPart("Oto podsumowanie najważniejszych faktów.")]),
    ]

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert info.instructions is not None
        assert "if ambiguous, keep the conversation's language" in info.instructions
        assert messages[:2] == history
        assert isinstance(messages[-1], ModelRequest)
        assert len(messages[-1].parts) == 1
        assert isinstance(messages[-1].parts[0], UserPromptPart)
        assert messages[-1].parts[0].content == "OK"
        return ModelResponse(parts=[TextPart("Synthetic follow-up inspection complete.")])

    built = build_agent(rendered, _model_spec(), organization_id=uuid4())
    with built.agent.override(model=FunctionModel(respond)):
        await built.agent.run("OK", deps=built.deps, message_history=history)
