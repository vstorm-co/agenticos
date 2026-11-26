"""Write auditable case rows and compare the same cases across arms."""

import json
import math
import random
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import BaseModel
from retrieval import Evidence

Arm = Literal[
    "bm25",
    "agenticos-legacy",
    "agenticos-ledger",
    "agenticos-maintenance",
    "mem0",
    "hindsight",
]
ARMS = (
    "bm25",
    "agenticos-legacy",
    "agenticos-ledger",
    "agenticos-maintenance",
    "mem0",
    "hindsight",
)


class Header(BaseModel):
    format: Literal[1] = 1
    manifest: str
    arm: Arm
    label: str
    git_sha: str
    top_k: int
    evidence_chars: int
    case_ids: list[str]


class Result(BaseModel):
    question_id: str
    category: str
    question: str
    date: datetime
    evidence: list[Evidence]
    ingest_ms: float | None
    recall_ms: float | None
    cost_usd: float | None
    metrics: dict[str, float | None]
    technical_error: str | None = None


def load_report(path: Path) -> tuple[Header, dict[str, Result]]:
    with path.open(encoding="utf-8") as stream:
        header = Header.model_validate_json(stream.readline())
        rows: dict[str, Result] = {}
        for line in stream:
            row = Result.model_validate_json(line)
            if row.question_id in rows:
                raise ValueError(f"{path.name}: duplicate result for {row.question_id}.")
            rows[row.question_id] = row
    if list(rows) != header.case_ids:
        raise ValueError(f"{path.name}: incomplete report or different case order.")
    return header, rows


def percentile(values: Sequence[float], fraction: float) -> float | None:
    return sorted(values)[math.ceil(fraction * len(values)) - 1] if values else None


def bootstrap(deltas: list[float], seed: int) -> dict[str, float | int | None]:
    if len(deltas) <= 1:
        return {
            "n": len(deltas),
            "delta": deltas[0] if deltas else None,
            "low": None,
            "high": None,
        }
    rng = random.Random(seed)  # noqa: S311 - Reproducible confidence interval.
    samples = sorted(mean(rng.choices(deltas, k=len(deltas))) for _ in range(2_000))
    return {
        "n": len(deltas),
        "delta": mean(deltas),
        "low": samples[49],
        "high": samples[1949],
    }


def summarize(rows: Iterable[Result]) -> dict[str, object]:
    selected = list(rows)
    valid = [row for row in selected if row.technical_error is None]
    recall = [row.recall_ms for row in valid if row.recall_ms is not None]
    ingest = [row.ingest_ms for row in valid if row.ingest_ms is not None]
    costs = [row.cost_usd for row in selected if row.cost_usd is not None]
    metrics: dict[str, float | None] = {}
    for metric in ("hit", "recall", "all_evidence", "mrr", "empty", "provenance"):
        values = [value for row in valid if (value := row.metrics.get(metric)) is not None]
        metrics[metric] = mean(values) if values else None
    return {
        "cases": len(selected),
        "technical_failures": len(selected) - len(valid),
        "metrics": metrics,
        "recall_ms_p50": percentile(recall, 0.5),
        "recall_ms_p95": percentile(recall, 0.95),
        "ingest_ms_p95": percentile(ingest, 0.95),
        "known_cost_usd": sum(costs) if costs else None,
        "unknown_cost_cases": len(selected) - len(costs),
    }


def official_grades(path: Path, ids: set[str]) -> tuple[str, dict[str, bool]]:
    grades: dict[str, bool] = {}
    models: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            key, label = row["question_id"], row["autoeval_label"]["label"]
            if key in grades or type(label) is not bool:
                raise ValueError(f"{path.name}: duplicate question or non-binary grade.")
            model = row["autoeval_label"]["model"]
            if not isinstance(model, str) or not model:
                raise ValueError(f"{path.name}: missing judge model.")
            models.add(model)
            grades[key] = label
    if grades.keys() != ids:
        raise ValueError(f"{path.name}: grade IDs differ from the comparison slice.")
    if len(models) != 1:
        raise ValueError(f"{path.name}: expected one pinned judge model.")
    return models.pop(), grades


def compare(paths: list[Path], judged: list[Path]) -> dict[str, object]:
    reports = [load_report(path) for path in paths]
    reference, baseline = reports[0]
    if judged and len(judged) != len(paths):
        raise ValueError("Supply one --grade per report, in report order.")
    grade_reports = [official_grades(path, set(baseline)) for path in judged]
    models = {model for model, _ in grade_reports}
    if len(models) > 1:
        raise ValueError("Use the same judge model for every arm.")
    grades = [rows for _, rows in grade_reports]
    categories = sorted({row.category for row in baseline.values()})
    arms: list[dict[str, object]] = []
    for index, (header, rows) in enumerate(reports):
        if (
            header.manifest != reference.manifest
            or header.case_ids != reference.case_ids
            or header.top_k != reference.top_k
            or header.evidence_chars != reference.evidence_chars
            or any(
                (row.category, row.question, row.date)
                != (baseline[key].category, baseline[key].question, baseline[key].date)
                for key, row in rows.items()
            )
        ):
            raise ValueError("Reports must share the same frozen cases and evidence budget.")
        paired_recall = [
            current - original
            for key, row in rows.items()
            if row.technical_error is None
            and baseline[key].technical_error is None
            and (current := row.metrics.get("recall")) is not None
            and (original := baseline[key].metrics.get("recall")) is not None
        ]
        arm: dict[str, object] = {
            "run": header.model_dump(mode="json"),
            "overall": summarize(rows.values()),
            "by_category": {
                group: summarize(row for row in rows.values() if row.category == group)
                for group in categories
            },
            "recall_delta_vs_first_95pct_ci": bootstrap(paired_recall, seed=17),
        }
        if grades:
            current_grades = grades[index]
            if any(row.technical_error for row in rows.values()):
                raise ValueError("Grade complete retrieval runs with no technical errors.")
            arm["answer_accuracy"] = mean(current_grades.values())
            arm["answer_accuracy_by_category"] = {
                group: mean(
                    current_grades[key] for key, row in rows.items() if row.category == group
                )
                for group in categories
            }
            arm["answer_delta_vs_first_95pct_ci"] = bootstrap(
                [float(current_grades[key]) - float(grades[0][key]) for key in rows],
                seed=17,
            )
        arms.append(arm)
    return {
        "baseline": reference.label,
        "manifest": reference.manifest,
        "judge_model": next(iter(models), None),
        "arms": arms,
    }
