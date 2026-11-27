"""Validate a local LongMemEval file and freeze a reproducible comparison slice."""

import hashlib
import json
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class RawCase(BaseModel):
    question_id: str
    question_type: str
    question: str = Field(min_length=1)
    question_date: str
    haystack_session_ids: list[str]
    haystack_dates: list[str]
    haystack_sessions: list[list[Turn]]
    answer_session_ids: list[str]


class Manifest(BaseModel):
    version: Literal[1] = 1
    dataset_sha256: str
    seed: int
    case_ids: list[str] = Field(min_length=1)
    top_k: int = Field(gt=0, le=100)
    evidence_chars: int = Field(gt=0, le=100_000)


@dataclass(frozen=True)
class Session:
    id: str
    date: datetime
    turns: tuple[Turn, ...]

    @property
    def text(self) -> str:
        return "\n".join(f"{turn.role}: {turn.content}" for turn in self.turns)


@dataclass(frozen=True)
class Query:
    """The adapter input deliberately excludes answers and original session IDs."""

    question: str
    date: datetime
    sessions: tuple[Session, ...]


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    query: Query
    gold: frozenset[str]
    future_sessions: int


def parse_date(value: str) -> datetime:
    value = re.sub(r"\s+\([A-Za-z]{3}\)", "", value.strip())
    date = datetime.fromisoformat(value.replace("/", "-"))
    return date.astimezone(UTC) if date.tzinfo else date.replace(tzinfo=UTC)


def read_dataset(path: Path) -> tuple[str, dict[str, dict[str, object]]]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    records = json.loads(data)
    if not isinstance(records, list) or not records:
        raise ValueError("Expected a nonempty LongMemEval JSON array.")
    indexed: dict[str, dict[str, object]] = {}
    for row in records:
        if not isinstance(row, dict):
            raise TypeError("Expected a JSON object for each LongMemEval case.")
        case_id = row.get("question_id")
        if not isinstance(case_id, str) or not case_id or case_id in indexed:
            raise ValueError("Question IDs must be nonempty, unique strings.")
        if not isinstance(row.get("question_type"), str):
            raise TypeError(f"{case_id}: missing question type.")
        indexed[case_id] = row
    return digest, indexed


def sample_ids(records: dict[str, dict[str, object]], limit: int, seed: int) -> list[str]:
    """Sample all available categories round-robin, including abstention."""
    if not 1 <= limit <= len(records):
        raise ValueError(f"Case limit must be between 1 and {len(records)}.")
    groups: dict[str, list[str]] = defaultdict(list)
    for case_id, row in sorted(records.items()):
        category = "abstention" if case_id.endswith("_abs") else str(row["question_type"])
        groups[category].append(case_id)
    rng = random.Random(seed)  # noqa: S311 - Reproducible sample order.
    categories = sorted(groups)
    rng.shuffle(categories)
    for instances in groups.values():
        rng.shuffle(instances)
    selected = []
    while len(selected) < limit:
        for category in categories:
            if instances := groups[category]:
                selected.append(instances.pop())
                if len(selected) == limit:
                    break
    return selected


def make_case(row: dict[str, object]) -> Case:
    raw = RawCase.model_validate(row)
    cutoff = parse_date(raw.question_date)
    order = sorted(
        zip(
            raw.haystack_session_ids,
            map(parse_date, raw.haystack_dates),
            raw.haystack_sessions,
            strict=True,
        ),
        key=lambda entry: entry[1],
    )
    gold_ids = set(raw.answer_session_ids)
    is_abstention = raw.question_id.endswith("_abs")
    if is_abstention == bool(gold_ids):
        raise ValueError(f"{raw.question_id}: unexpected answer-session labels.")
    sessions: dict[str, Session] = {}
    future = 0
    for original_id, date, turns in order:
        if date > cutoff:
            future += 1
            continue
        if existing := sessions.get(original_id):
            if existing.date != date or existing.turns != tuple(turns):
                raise ValueError(f"{raw.question_id}: ambiguous repeated session ID.")
            continue
        sessions[original_id] = Session(f"s{len(sessions) + 1:05}", date, tuple(turns))
    if not gold_ids <= sessions.keys():
        raise ValueError(f"{raw.question_id}: an answer session is missing before the cutoff.")
    return Case(
        raw.question_id,
        "abstention" if is_abstention else raw.question_type,
        Query(raw.question, cutoff, tuple(sessions.values())),
        frozenset(sessions[source].id for source in gold_ids),
        future,
    )


def load_cases(path: Path, manifest: Manifest) -> list[Case]:
    digest, records = read_dataset(path)
    if digest != manifest.dataset_sha256:
        raise ValueError("Dataset SHA-256 differs from the frozen manifest.")
    if len(set(manifest.case_ids)) != len(manifest.case_ids):
        raise ValueError("Manifest contains duplicate case IDs.")
    return [make_case(records[case_id]) for case_id in manifest.case_ids]


def fingerprint(manifest: Manifest) -> str:
    return hashlib.sha256(manifest.model_dump_json().encode()).hexdigest()
