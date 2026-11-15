"""Partition identities and leakage checks, independent of a database or model."""

from decimal import Decimal
from uuid import UUID

from app.services.improvement_data import (
    CaseIdentity,
    case_partition,
    drawn_holdout,
    holdout_count,
    input_hash,
    measurable,
    measurement,
)


def test_partition_depends_only_on_identity_and_extreme_shares_are_exact() -> None:
    ids = [UUID(int=number) for number in range(1, 100)]
    frozen = {case_id: case_partition(case_id, Decimal("0.5")) for case_id in ids[:10]}
    assert {case_partition(case_id, Decimal("0.5")) for case_id in ids} == {"train", "holdout"}
    assert frozen == {case_id: case_partition(case_id, Decimal("0.5")) for case_id in ids[:10]}
    assert {case_partition(case_id, Decimal(0)) for case_id in ids} == {"train"}
    assert {case_partition(case_id, Decimal(1)) for case_id in ids} == {"holdout"}


def test_an_attempt_draws_exactly_its_share_and_the_same_seed_draws_the_same_questions() -> None:
    ids = [UUID(int=number) for number in range(1, 12)]
    first = drawn_holdout(ids, share=Decimal("0.5"), seed=7)
    assert len(first) == 6 and set(first) <= set(ids)
    assert drawn_holdout(ids, share=Decimal("0.5"), seed=7) == first
    assert set(drawn_holdout(ids, share=Decimal("0.5"), seed=8)) != set(first)
    assert drawn_holdout(ids, share=Decimal(0), seed=7) == []
    assert set(drawn_holdout(ids, share=Decimal(1), seed=7)) == set(ids)


def test_input_hash_evenly_handles_case_whitespace_and_unicode_width() -> None:
    assert input_hash("  \uff32\uff25\uff26\uff35\uff2e\uff24\n\tPolicy? ") == input_hash(
        "refund policy?"
    )
    assert input_hash("refund policy") != input_hash("refund policy?")


def test_training_never_decides_the_verdict_and_evidence_copies_are_excluded() -> None:
    source = UUID(int=20)
    cases = [
        CaseIdentity(UUID(int=1), "train", "Training question", None, True),
        CaseIdentity(UUID(int=2), "holdout", "  REFUND   policy? ", None, True),
        CaseIdentity(UUID(int=3), "holdout", "A generated paraphrase", source, True),
        CaseIdentity(UUID(int=4), "holdout", "New question", None, True),
        CaseIdentity(UUID(int=5), "holdout", "Nothing grades this", None, False),
    ]
    result = measurement(
        cases,
        evidence_inputs=["refund policy?"],
        evidence_run_ids=[source],
        already_excluded=[UUID(int=6)],
    )
    assert result.train_case_ids == [UUID(int=1)]
    assert result.holdout_case_ids == [UUID(int=4), UUID(int=5)]
    assert result.excluded_case_ids == [UUID(int=6), UUID(int=2), UUID(int=3)]
    assert result.gradable_holdout == 1 and result.minimum_holdout == 5


def test_empty_measurement_requires_more_questions() -> None:
    result = measurement([], evidence_inputs=[], evidence_run_ids=[])
    assert result.gradable_holdout == 0
    assert result.train_case_ids == result.holdout_case_ids == result.excluded_case_ids == []


def test_held_out_copy_of_a_training_question_is_excluded_before_learning() -> None:
    result = measurement(
        [
            CaseIdentity(UUID(int=1), "train", "Refund policy?", None, True),
            CaseIdentity(UUID(int=2), "holdout", " REFUND   policy? ", None, True),
            CaseIdentity(UUID(int=3), "holdout", "Different question", None, True),
        ],
        evidence_inputs=[],
        evidence_run_ids=[],
    )
    assert result.holdout_case_ids == [UUID(int=3)]
    assert result.excluded_case_ids == [UUID(int=2)]


def test_an_attempt_keeps_aside_what_its_check_can_measure_before_anything_else() -> None:
    ids = [UUID(int=number) for number in range(1, 11)]
    can = set(ids[:4])
    for seed in range(20):
        drawn = drawn_holdout(ids, share=Decimal("0.5"), seed=seed, measurable=can)
        assert len(drawn) == holdout_count(10, Decimal("0.5")) == 5
        assert can <= set(drawn)
    several = set(ids[:8])
    assert (
        len(
            {
                frozenset(drawn_holdout(ids, share=Decimal("0.5"), seed=seed, measurable=several))
                for seed in range(20)
            }
        )
        > 1
    )
    assert all(
        set(drawn_holdout(ids, share=Decimal("0.5"), seed=seed, measurable=several)) <= several
        for seed in range(20)
    )


def test_a_question_is_measurable_only_when_gradable_asked_once_and_not_from_the_evidence() -> None:
    source = UUID(int=20)
    cases = [
        CaseIdentity(UUID(int=1), "holdout", "New question", None, True),
        CaseIdentity(UUID(int=2), "holdout", "  REFUND   policy? ", None, True),
        CaseIdentity(UUID(int=3), "holdout", "A generated paraphrase", source, True),
        CaseIdentity(UUID(int=4), "holdout", "Nothing grades this", None, False),
        CaseIdentity(UUID(int=5), "train", "Asked twice", None, True),
        CaseIdentity(UUID(int=6), "holdout", "asked   TWICE", None, True),
    ]
    assert measurable(cases, evidence_inputs=["refund policy?"], evidence_run_ids=[source]) == {
        UUID(int=1)
    }
