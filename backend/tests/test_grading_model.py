"""Which model a new judge grades on: the organization's choice, or one costing more."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.credential import ModelProfile
from app.services import grading_model
from app.services.grading_model import grading_profile, output_price

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
_START = datetime(2026, 10, 1, tzinfo=UTC)

# Output dollars per million tokens, as the price snapshot would answer.
_PRICES = {
    "cheap": Decimal("0.60"),
    "agent": Decimal("2.00"),
    "step": Decimal("8.00"),
    "step-twin": Decimal("8.00"),
    "top": Decimal("40.00"),
}


def _profile(model: str, *, age: int = 0, chat: bool = True) -> ModelProfile:
    return ModelProfile(
        id=uuid.uuid4(),
        organization_id=ORG,
        label=model,
        model=model,
        provider="openai" if chat else "openai-tts",
        base_url=None,
        created_at=_START + timedelta(days=age),
    )


def _price(_usage: object, model: str, provider: str | None) -> Decimal | None:
    return _PRICES.get(model)


def _outputs(provider: str, model: str, *, base_url: str | None) -> SimpleNamespace:
    return SimpleNamespace(chat=provider == "openai")


async def _pick(
    profiles: list[ModelProfile],
    graded: list[ModelProfile | None],
    *,
    chosen: ModelProfile | None = None,
) -> ModelProfile | None:
    organization = SimpleNamespace(grading_model_profile_id=None if chosen is None else chosen.id)
    with (
        patch.object(grading_model, "price_request", new=_price),
        patch.object(grading_model, "model_outputs", new=_outputs),
        patch.object(
            grading_model.organization_repo, "get_by_id", new=AsyncMock(return_value=organization)
        ),
        patch.object(
            grading_model.credential_repo,
            "get_profile",
            new=AsyncMock(side_effect=lambda _db, profile_id, **_: chosen),
        ),
        patch.object(
            grading_model.credential_repo, "list_profiles", new=AsyncMock(return_value=profiles)
        ),
    ):
        return await grading_profile(MagicMock(), organization_id=ORG, graded=graded)


async def test_the_organization_s_grading_model_is_taken_whatever_it_costs() -> None:
    agent, cheap = _profile("agent"), _profile("cheap")
    assert await _pick([agent, cheap], [agent], chosen=cheap) is cheap


async def test_a_grading_model_that_cannot_chat_is_passed_over_for_a_dearer_one() -> None:
    agent, speech, step = _profile("agent"), _profile("top", chat=False), _profile("step")
    assert await _pick([agent, speech, step], [agent], chosen=speech) is step


async def test_without_a_choice_the_cheapest_model_dearer_than_the_agent_s_is_taken() -> None:
    agent, step, top = _profile("agent"), _profile("step"), _profile("top")
    assert await _pick([top, agent, step], [agent]) is step


async def test_the_dearer_of_the_draft_and_the_published_model_is_the_one_to_beat() -> None:
    agent, step, top = _profile("agent"), _profile("step"), _profile("top")
    assert await _pick([agent, step, top], [agent, step]) is top


async def test_between_two_equally_dear_models_the_older_is_taken() -> None:
    agent = _profile("agent")
    newer, older = _profile("step", age=5), _profile("step-twin", age=1)
    assert await _pick([agent, newer, older], [agent]) is older


@pytest.mark.parametrize(
    "graded",
    [
        [],
        [None],
        [_profile("unpriced")],
    ],
    ids=["no-agent-model", "unknown-agent-model", "unpriced-agent-model"],
)
async def test_nothing_is_chosen_without_a_priced_model_to_beat(graded) -> None:
    assert await _pick([_profile("top")], graded) is None


async def test_nothing_is_chosen_when_no_model_costs_more() -> None:
    top, cheap = _profile("top"), _profile("cheap")
    assert await _pick([top, cheap], [top]) is None


def test_a_profile_is_priced_by_what_it_costs_to_write_with() -> None:
    profile = _profile("gpt-4o-mini")
    price = output_price(profile)
    assert price is not None and price > 0
