"""The three decision steps: a typed question to Jev, answered with a confidence.

The model is a `FunctionModel` standing in for `TypeSafeModel`: it answers the
one output field the way Jev's adapter does, with the per-field confidence,
distribution and rubric position in `provider_details`. What is under test is
what the steps ask, what they hand on and which port they leave by - and every
way they refuse, before or instead of asking.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, SecretKind
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes import _decide
from app.workflows.nodes._decide import DecisionConfig, DecisionInput, answer_schema, check_key
from app.workflows.nodes.decide_choose._handler import ChooseConfig
from app.workflows.nodes.decide_choose._handler import handle as choose
from app.workflows.nodes.decide_choose._handler import routes as choose_routes
from app.workflows.nodes.decide_score._handler import ScoreConfig
from app.workflows.nodes.decide_score._handler import handle as score
from app.workflows.nodes.decide_score._handler import routes as score_routes
from app.workflows.nodes.decide_yes_no._handler import handle as yes_no
from app.workflows.nodes.decide_yes_no._handler import routes as yes_no_routes

pytestmark = pytest.mark.anyio

KEY = uuid.uuid4()
BASE = {"question": "Is this urgent?", "secret_id": str(KEY)}
TEXT = DecisionInput(text="The site is down for every customer.")


class _Jev:
    """Answers the one field it is asked, and records what it was asked."""

    def __init__(self, answer: Any, *, confidence: float, **details: Any) -> None:
        self.answer = answer
        self.details = {"confidence": {"answer": confidence}, **details}
        self.asked: list[dict[str, Any]] = []
        self.texts: list[str] = []

    def model(self, name: str, api_key: str) -> FunctionModel:
        self.name, self.key = name, api_key

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            tool = info.output_tools[0]
            self.asked.append(tool.parameters_json_schema)
            self.texts += [
                str(part.content)
                for message in messages
                for part in getattr(message, "parts", [])
                if part.part_kind == "user-prompt"
            ]
            return ModelResponse(
                parts=[ToolCallPart(tool_name=tool.name, args={"answer": self.answer})],
                provider_details=self.details,
            )

        return FunctionModel(respond)


def _dispatch() -> context.DispatchContext:
    return context.DispatchContext(
        organization_id=uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner"),
        resumed_agent_run_id=None,
    )


@pytest.fixture
def jev(monkeypatch: pytest.MonkeyPatch):
    """Install a Jev and a usable TypeSafe key; the key is `None` to take it away."""
    key = {"row": MagicMock(sealed_secret="sealed", key_version=1)}

    @asynccontextmanager
    async def session() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    monkeypatch.setattr(_decide, "get_worker_db_context", session)
    monkeypatch.setattr(_decide, "_usable_key", AsyncMock(side_effect=lambda *_a: key["row"]))
    monkeypatch.setattr(
        _decide, "unseal_kind", lambda *_a, **_k: ApiKeySecret(api_key="ts-key-1234")
    )

    def install(answer: Any, *, confidence: float = 0.9, **details: Any) -> _Jev:
        model = _Jev(answer, confidence=confidence, **details)
        monkeypatch.setattr(_decide, "model_factory", model.model)
        return model

    install.key = key  # type: ignore[attr-defined]
    return install


async def _ask(handle, config: DecisionConfig) -> Any:
    with context.dispatching_as(_dispatch()):
        return await handle(config, TEXT)


class TestYesOrNo:
    async def test_a_confident_yes_leaves_by_yes(self, jev):
        model = jev(True, confidence=0.92)
        result = await _ask(yes_no, DecisionConfig.model_validate(BASE))

        assert isinstance(result, Completed)
        assert result.output.model_dump() == {"answer": True, "confidence": 0.92, "unsure": False}
        assert yes_no_routes(result.output.model_dump()) == {"yes"}
        # The question is the field's description, the text is the prompt, the key is the vault's.
        assert model.asked[0]["properties"]["answer"] == {
            "type": "boolean",
            "description": "Is this urgent?",
        }
        assert model.texts == [TEXT.text]
        assert (model.name, model.key) == ("jev-latest", "ts-key-1234")

    async def test_a_no_below_the_floor_is_unsure(self, jev):
        jev(False, confidence=0.3)
        result = await _ask(yes_no, DecisionConfig.model_validate(BASE))

        assert result.output.unsure is True
        assert yes_no_routes(result.output.model_dump()) == {"unsure"}
        assert yes_no_routes({"answer": False, "unsure": False}) == {"no"}
        assert yes_no_routes(None) == frozenset()


class TestChooseOne:
    CONFIG = {
        **BASE,
        "question": "Which team handles this?",
        "options": [{"value": "billing", "description": "Invoices and refunds"}, {"value": "tech"}],
    }

    async def test_the_pick_comes_with_its_distribution(self, jev):
        model = jev(
            "billing", confidence=0.8, probabilities={"answer": {"billing": 0.9, "tech": 0.1}}
        )
        result = await _ask(choose, ChooseConfig.model_validate(self.CONFIG))

        assert result.output.model_dump() == {
            "choice": "billing",
            "confidence": 0.8,
            "probabilities": {"billing": 0.9, "tech": 0.1},
            "unsure": False,
        }
        assert choose_routes(result.output.model_dump()) == {"out"}
        # Each option is a `const` with its meaning, which is how Jev reads a pick-one.
        assert model.asked[0]["properties"]["answer"]["anyOf"] == [
            {"const": "billing", "description": "Invoices and refunds"},
            {"const": "tech"},
        ]

    async def test_an_unsure_pick_leaves_by_unsure(self, jev):
        jev("tech", confidence=0.2)
        result = await _ask(choose, ChooseConfig.model_validate(self.CONFIG))
        assert choose_routes(result.output.model_dump()) == {"unsure"}
        assert result.output.probabilities == {}
        assert choose_routes(None) == frozenset()

    def test_two_options_of_one_value_are_refused(self):
        with pytest.raises(ValidationError, match="same value"):
            ChooseConfig.model_validate({**BASE, "options": [{"value": "a"}, {"value": "a"}]})


class TestScore:
    CONFIG = {**BASE, "levels": ["not urgent", "soon", "now"]}

    async def test_the_score_is_the_nearest_level_and_says_where_between(self, jev):
        model = jev(2, confidence=0.7, scores={"answer": 1.8})
        result = await _ask(score, ScoreConfig.model_validate(self.CONFIG))

        assert result.output.model_dump() == {
            "score": 2,
            "position": 1.8,
            "confidence": 0.7,
            "unsure": False,
        }
        assert score_routes(result.output.model_dump()) == {"out"}
        assert model.asked[0]["properties"]["answer"]["anyOf"][0] == {
            "const": 0,
            "description": "not urgent",
        }

    async def test_a_score_with_no_position_reported_sits_on_its_level(self, jev):
        jev(1, confidence=0.1)
        result = await _ask(score, ScoreConfig.model_validate(self.CONFIG))
        assert (result.output.position, result.output.unsure) == (1.0, True)


class TestRefusals:
    @pytest.mark.parametrize("handle", [yes_no, choose, score])
    async def test_an_unconfigured_step_asks_nothing(self, handle, jev):
        model = jev(True)
        with context.dispatching_as(_dispatch()):
            result = await handle(None, None)
        assert isinstance(result, Failed) and result.error.code == "DECISION_NOT_CONFIGURED"
        assert model.asked == []

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("handle", "config"),
        [
            (yes_no, DecisionConfig.model_validate(BASE)),
            (choose, ChooseConfig.model_validate(TestChooseOne.CONFIG)),
            (score, ScoreConfig.model_validate(TestScore.CONFIG)),
        ],
        ids=["yes-no", "choose", "score"],
    )
    async def test_a_key_no_longer_usable_stops_the_step_before_it_asks(self, jev, handle, config):
        model = jev(True)
        jev.key["row"] = None
        result = await _ask(handle, config)
        assert isinstance(result, Failed) and result.error.code == "SECRET_NOT_USABLE"
        assert model.asked == []

    async def test_a_deployment_without_the_sdk_says_so(self, jev, monkeypatch):
        jev(True)

        def missing(*_args: Any) -> Any:
            raise ImportError("typesafe")

        monkeypatch.setattr(_decide, "model_factory", missing)
        result = await _ask(yes_no, DecisionConfig.model_validate(BASE))
        assert isinstance(result, Failed) and result.error.code == "DECISION_MODEL_UNAVAILABLE"

    async def test_a_model_that_does_not_answer_is_a_retryable_failure(self, jev, monkeypatch):
        jev(True)

        def broken(*_args: Any) -> FunctionModel:
            def respond(*_a: Any) -> ModelResponse:
                raise RuntimeError("503 https://api.typesafe.ai?key=ts-key-1234")

            return FunctionModel(respond)

        monkeypatch.setattr(_decide, "model_factory", broken)
        result = await _ask(yes_no, DecisionConfig.model_validate(BASE))
        assert isinstance(result, Failed) and result.error.code == "DECISION_FAILED"
        assert result.error.retryable is True
        assert "ts-key" not in str(result.error)


class TestTheKey:
    def _row(self, **fields: Any) -> MagicMock:
        return MagicMock(kind=SecretKind.API_KEY.value, purpose="typesafe", **fields)

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("row", "readable", "usable"),
        [
            ("typesafe", True, True),
            ("other-purpose", True, False),
            ("other-kind", True, False),
            ("missing", True, False),
            ("typesafe", False, False),
        ],
    )
    async def test_only_a_typesafe_api_key_the_caller_may_read_is_used(
        self, monkeypatch, row, readable, usable
    ):
        rows = {
            "typesafe": self._row(),
            "other-purpose": MagicMock(kind=SecretKind.API_KEY.value, purpose="openai"),
            "other-kind": MagicMock(kind=SecretKind.HTTP_CREDENTIAL.value, purpose="typesafe"),
            "missing": None,
        }
        monkeypatch.setattr(
            _decide.organization_secret_repo, "get", AsyncMock(return_value=rows[row])
        )
        monkeypatch.setattr(_decide, "resolve_access", AsyncMock(return_value=readable))
        ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")

        problems = await check_key(MagicMock(), ctx, DecisionConfig.model_validate(BASE))

        assert (problems == []) is usable
        if not usable:
            assert problems[0][0] == "secret_id"

    async def test_a_config_of_another_step_is_not_this_checks_to_judge(self):
        assert await check_key(MagicMock(), MagicMock(), MagicMock()) == []


def test_the_question_is_the_one_fields_description():
    assert answer_schema("Why?", {"type": "boolean"}) == {
        "type": "object",
        "properties": {"answer": {"type": "boolean", "description": "Why?"}},
        "required": ["answer"],
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    ("definition_id", "exclusive"),
    [
        ("decide.yes_no", True),
        ("decide.choose", True),
        ("decide.score", True),
        ("control.foreach", False),
    ],
)
def test_a_merge_may_rejoin_a_decision_steps_branches(definition_id, exclusive):
    """A decision takes exactly one of its ports per run, as `logic.if` does, so its
    branches are exclusive and a merge after them publishes; a loop's are not."""
    from app.workflows import _registry
    from app.workflows.graph.model import NodeInstance, NodePosition
    from app.workflows.graph.validate import _branches_exclusively

    node = NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config={},
        layout=NodePosition(x=0, y=0),
    )
    assert _branches_exclusively(node, _registry.get(definition_id, 1)) is exclusive
