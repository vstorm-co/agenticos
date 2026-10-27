"""Stable dataset partitions and the questions an improvement may measure."""

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from app.schemas.dataset import CasePartitionLiteral
from app.schemas.eval_run import ImprovementMeasurement

MIN_HOLDOUT_CASES = 5
_SPACE = re.compile(r"\s+")


def case_partition(case_id: UUID, holdout_share: Decimal) -> CasePartitionLiteral:
    """Assign a new identity once. Edits copy the stored assignment instead.

    SHA-256 provides a uniform bucket for new identities. Existing assignments,
    including the `0196_improvement_holdout.py` backfill, are stored and copied
    across revisions; changing the allocator must never move an existing case
    between train and holdout.
    """
    bucket = int(hashlib.sha256(str(case_id).encode()).hexdigest()[:8], 16)
    return "holdout" if Decimal(bucket) < holdout_share * (2**32) else "train"


def holdout_count(cases: int, share: Decimal) -> int:
    """How many questions an attempt keeps aside: the dataset's share, rounded half up."""
    return int((share * cases).to_integral_value(rounding=ROUND_HALF_UP))


def drawn_holdout(
    case_ids: Sequence[UUID],
    *,
    share: Decimal,
    seed: int,
    measurable: Collection[UUID] = (),
) -> list[UUID]:
    """An attempt's own measured questions: exactly the dataset's share of them, drawn by `seed`.

    Drawn as one set rather than question by question, so a small dataset gets
    its whole share instead of whatever each question's coin gave it, and the
    same seed always draws the same questions. The `measurable` questions are
    drawn first: one the check would leave out only takes the place of one it
    could measure when there are too few of those.
    """
    ranked = sorted(
        case_ids,
        key=lambda case_id: (
            case_id not in measurable,
            hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest(),
        ),
    )
    return ranked[: holdout_count(len(case_ids), share)]


def input_hash(text: str) -> str:
    normalized = _SPACE.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


@dataclass(frozen=True)
class CaseIdentity:
    case_id: UUID
    partition: CasePartitionLiteral
    input: str
    source_run_id: UUID | None
    gradable: bool


def measurable(
    cases: Sequence[CaseIdentity],
    *,
    evidence_inputs: Collection[str],
    evidence_run_ids: Collection[UUID],
) -> set[UUID]:
    """The questions a check could measure wherever a draw puts the others.

    Gradable, asked once in the set - a copy left on the learning side would
    exclude it - and neither taken from nor a copy of the session's evidence.
    """
    asked = Counter(input_hash(case.input) for case in cases)
    copied = {input_hash(text) for text in evidence_inputs}
    sources = set(evidence_run_ids)
    return {
        case.case_id
        for case in cases
        if case.gradable
        and case.source_run_id not in sources
        and asked[question := input_hash(case.input)] == 1
        and question not in copied
    }


def measurement(
    cases: Sequence[CaseIdentity],
    *,
    evidence_inputs: Collection[str],
    evidence_run_ids: Collection[UUID],
    already_excluded: Sequence[UUID] = (),
) -> ImprovementMeasurement:
    """Separate learning questions from untouched, gradable measurement questions.

    Provenance alone is insufficient: hand-entered, imported and generated
    copies of a source question must not become a fresh test of that question.
    Training cases still run so the next round can learn how their results changed.
    """
    hashes = {input_hash(text) for text in evidence_inputs}
    hashes.update(input_hash(case.input) for case in cases if case.partition == "train")
    source_ids = set(evidence_run_ids)
    train: list[UUID] = []
    held: list[UUID] = []
    excluded = list(already_excluded)
    gradable = 0
    for case in cases:
        if case.partition == "train":
            train.append(case.case_id)
        elif input_hash(case.input) in hashes or case.source_run_id in source_ids:
            excluded.append(case.case_id)
        else:
            held.append(case.case_id)
            gradable += case.gradable
    return ImprovementMeasurement(
        train_case_ids=train,
        holdout_case_ids=held,
        excluded_case_ids=excluded,
        gradable_holdout=gradable,
        minimum_holdout=MIN_HOLDOUT_CASES,
    )
