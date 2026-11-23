"""The rules a search attempt draws, scores, ranks and hands on its variants by."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.spec import AgentSpec
from app.db.models.improvement import ImprovementSearchVariant, SearchProgress, SearchVariantStatus
from app.schemas.improvement import ImprovementStart, ImprovementTarget, SearchOptions
from app.schemas.scoring import DatasetScoring, ScorerResult
from app.services import authoring_hunks
from app.services.improvement_search import (
    _close_generation,
    _grading,
    _proposal_price,
    case_share,
    draw_questions,
    keeps_placeholders,
    search_left,
    search_settings,
    variant_hash,
    variant_hunks,
    winner,
)
from app.services.model_profile import ModelProfileService
from app.worker.jobs import SEARCH_IMPROVEMENT, Pool

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _result(status: str, *, required: bool = True) -> ScorerResult:
    return ScorerResult(
        scorer="check", name=f"check-{uuid4().hex[:4]}", required=required, status=status, reason=""
    )


def _variant(
    generation: int, score: float | None, *, text: str = "x", status: str = "scored"
) -> ImprovementSearchVariant:
    return ImprovementSearchVariant(
        id=uuid4(),
        generation=generation,
        train_score=score,
        instructions=text,
        status=status,
        created_at=datetime.now(UTC) + timedelta(seconds=generation),
    )


def _progress(**values: object) -> SearchProgress:
    base = SearchProgress(
        settings=search_settings(SearchOptions(budget_usd=Decimal("2"))),
        case_ids=[],
        spent_before_usd="1",
        generation=0,
        closed_generation=-1,
        stale_generations=0,
        seed_score=0.5,
        best_before=None,
        cost_usd="0",
        stop_reason=None,
        chosen_variant_id=None,
    )
    return SearchProgress(**{**base, **values})


def test_every_variant_is_scored_on_the_same_draw_of_training_questions():
    cases = [uuid4() for _ in range(30)]
    drawn = draw_questions(cases, size=12, seed=7)
    assert len(drawn) == 12 and set(drawn) <= set(cases)
    assert draw_questions(list(reversed(cases)), size=12, seed=7) == drawn
    assert draw_questions(cases, size=12, seed=8) != drawn
    assert sorted(draw_questions(cases[:5], size=12, seed=7), key=str) == sorted(cases[:5], key=str)


def test_a_case_scores_the_share_of_its_required_checks_that_passed():
    assert case_share([_result("pass"), _result("fail"), _result("pass", required=False)]) == 0.5
    assert case_share([_result("skipped"), _result("fail", required=False)]) is None
    assert case_share([]) is None


def test_a_variant_may_not_name_a_template_variable_its_instructions_did_not():
    seed = "Hello {{ user.name }}, it is {{date}}."
    assert keeps_placeholders(seed, "Hi {{user.name}}.")
    assert not keeps_placeholders(seed, "Hi {{secret}}.")


def test_the_same_text_has_one_identity_whatever_space_surrounds_it():
    assert variant_hash("Be brief.\n") == variant_hash("  Be brief.")
    assert variant_hash("Be brief.") != variant_hash("Be kind.")


@pytest.mark.parametrize(
    ("base", "variant"),
    [
        ("You answer refunds.\nBe brief.", "You answer refunds.\nBe brief.\nRefunds take 30 days."),
        ("A\nB\nC\n", "A\nX\nC\nD\n"),
        ("Drop me.\nKeep me.", "Keep me."),
        ("", "Something new."),
    ],
)
def test_a_variant_becomes_hunks_that_rebuild_it_from_the_base(base: str, variant: str):
    hunks = variant_hunks(base, variant, rationale="Found by search")
    assert hunks and all(h["kind"] == "instructions" and h["evidence"] == [] for h in hunks)
    rows = [
        SimpleNamespace(
            id=uuid4(),
            kind=h["kind"],
            status="pending",
            edited_text=None,
            new_text=h["new_text"],
            old_text=h["old_text"],
            context_before=h["context_before"],
            context_after=h["context_after"],
            base_start=h["base_start"],
            base_end=h["base_end"],
            position=index,
        )
        for index, h in enumerate(hunks)
    ]
    spec = AgentSpec(name="Clerk", instructions=base)
    projected, skipped = authoring_hunks.projection(spec, rows)
    assert not skipped
    assert projected.instructions == variant


def test_each_change_of_a_variant_applies_without_the_others():
    """A person may leave any change out at Changes; the rest must still anchor."""
    base = "A\nB\nC\nD\nE\n"
    hunks = variant_hunks(base, "A\nX\nC\nY\nE\n", rationale="")
    assert len(hunks) == 2
    for kept, expected in ((0, "A\nX\nC\nD\nE\n"), (1, "A\nB\nC\nY\nE\n")):
        h = hunks[kept]
        row = SimpleNamespace(
            id=uuid4(),
            kind=h["kind"],
            status="pending",
            edited_text=None,
            new_text=h["new_text"],
            old_text=h["old_text"],
            context_before=h["context_before"],
            context_after=h["context_after"],
            base_start=h["base_start"],
            base_end=h["base_end"],
            position=0,
        )
        projected, skipped = authoring_hunks.projection(
            AgentSpec(name="C", instructions=base), [row]
        )
        assert not skipped and projected.instructions == expected


def test_an_identical_variant_has_no_hunks():
    assert variant_hunks("Same.\n", "Same.\n", rationale="") == []


def test_the_search_starts_nothing_past_its_own_budget_or_the_sessions():
    progress = _progress(spent_before_usd="1")
    assert search_left(progress, spent=Decimal("1.5"), budget=Decimal("10")) == Decimal("1.5")
    assert search_left(progress, spent=Decimal("1.5"), budget=Decimal("2")) == Decimal("0.5")


def test_only_variants_that_beat_the_starting_instructions_win_best_first():
    seed = _variant(0, 0.5)
    tie_long = _variant(1, 0.8, text="a much longer text")
    tie_short = _variant(2, 0.8, text="short")
    worse = _variant(1, 0.4)
    pending = _variant(1, None, status=SearchVariantStatus.PENDING.value)
    failed = _variant(1, None, status=SearchVariantStatus.FAILED.value)
    assert winner([seed, tie_long, worse, tie_short, pending, failed], 0.5) == [
        tie_short,
        tie_long,
    ]
    assert winner([seed, tie_long], None) == []
    assert winner([seed, _variant(1, 0.5)], 0.5) == []


def test_a_round_counts_as_stale_when_it_finds_nothing_better():
    found = [_variant(1, 0.9), _variant(1, 0.6)]
    better = _close_generation(_progress(generation=1, best_before=0.5), found)
    assert better["stale_generations"] == 0 and better["closed_generation"] == 1
    assert _close_generation(better, found) is better
    stale = _close_generation(_progress(generation=1, best_before=0.9, stale_generations=1), found)
    assert stale["stale_generations"] == 2
    empty = _close_generation(_progress(generation=2, best_before=None), found)
    assert empty["stale_generations"] == 1
    first = _close_generation(_progress(generation=1, best_before=None), found)
    assert first["stale_generations"] == 0
    seed = _progress(generation=0)
    assert _close_generation(seed, found) is seed


def test_the_search_grades_on_the_chosen_model_and_keeps_the_rest_of_the_grading():
    pinned = DatasetScoring.model_validate({"judge": {"enabled": True, "pass_at": 3}})
    run = SimpleNamespace(pinned_scoring=pinned.model_dump(mode="json"))
    chosen = uuid4()
    options = search_settings(SearchOptions(budget_usd=Decimal(1), grading_model_profile_id=chosen))
    graded = _grading(run, options)  # ty: ignore[invalid-argument-type]
    assert graded.judge.model_profile_id == chosen and graded.judge.pass_at == 3
    unchanged = _grading(run, search_settings(SearchOptions(budget_usd=Decimal(1))))  # ty: ignore[invalid-argument-type]
    assert unchanged == pinned


def test_search_options_go_with_the_search_mode_only():
    dataset = uuid4()
    with pytest.raises(ValidationError, match="Search options go with the search mode"):
        ImprovementTarget(dataset_id=dataset, mode="search")
    with pytest.raises(ValidationError, match="Search options go with the search mode"):
        ImprovementTarget(dataset_id=dataset, search=SearchOptions(budget_usd=Decimal(1)))
    started = ImprovementStart(
        dataset_id=dataset,
        budget_usd=Decimal(5),
        mode="search",
        search=SearchOptions(budget_usd=Decimal(2)),
    )
    assert started.search is not None and started.search.max_variants == 40
    assert started.search.per_generation == 4 and started.search.minibatch == 12
    assert started.search.patience == 3


def test_a_search_unit_holds_an_eval_slot_briefly_and_one_per_organization():
    """The job's shape is what keeps searches from starving an organization's eval runs."""
    assert SEARCH_IMPROVEMENT.pool is Pool.EVAL
    assert SEARCH_IMPROVEMENT.timeout <= timedelta(minutes=15)
    assert SEARCH_IMPROVEMENT.max_attempts == 1


@pytest.mark.parametrize(
    ("model", "profile", "expected"),
    [
        ("gpt-4o-mini", uuid4(), None),
        ("not-a-priced-model", uuid4(), Decimal("0.10")),
        ("gpt-4o-mini", None, Decimal("0.10")),
    ],
)
async def test_a_round_of_proposals_is_priced_at_the_improvers_model_or_the_fallback(
    model: str, profile, expected: Decimal | None
):
    resolve = AsyncMock(return_value=SimpleNamespace(model=model, provider="openai"))
    with patch.object(ModelProfileService, "resolve", new=resolve):
        price = await _proposal_price(
            AsyncMock(), AsyncMock(), profile, "x" * 4000, count=2, seed="y" * 400
        )
    if expected is None:
        assert Decimal(0) < price < Decimal("0.10")
    else:
        assert price == expected


def test_a_variant_names_itself_by_attempt_generation_and_score():
    variant = _variant(2, 0.75)
    assert "generation=2" in repr(variant) and "score=0.75" in repr(variant)
