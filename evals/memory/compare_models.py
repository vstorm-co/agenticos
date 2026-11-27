"""Compare OpenRouter models on AgenticOS memory tools and maintenance extraction."""

import argparse
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import UUID

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
PERSONAL = ROOT / "evals" / "personal" / "run.py"
TOOLS = (
    "agenticos-remember-client",
    "agenticos-self-note",
    "agenticos-project-no-workspace",
    "agenticos-as-of-tool",
    "agenticos-confirm-share",
    "explicit-memory-file-read",
    "memory-oneoff",
    "durable-style-implicit",
)
LIVE = ("live-memory-remember", "live-memory-correct_memory", "live-memory-recall")
SONNET = "openrouter:anthropic/claude-sonnet-5.5"
SOL = "openrouter:openai/gpt-6.2-sol"
HAIKU = "openrouter:anthropic/claude-haiku-5.5"
LUNA = "openrouter:openai/gpt-6-luna"


class Receipt(BaseModel):
    """The fields in the personal runner's case receipts used by the scorecard."""

    case: str
    model: str
    errors: list[str]
    latency_ms: int | None = Field(default=None, ge=0)
    cost_usd: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    cost_is_partial: bool = True


@dataclass(frozen=True)
class Phase:
    name: str
    requested: int
    receipts: list[Receipt]
    wall_seconds: float
    exit_code: int | None
    receipts_file: str | None
    reason: str | None = None


def summarize(phases: list[Phase]) -> dict[str, object]:
    rows = [row for phase in phases for row in phase.receipts]
    durations = sorted(row.latency_ms for row in rows if row.latency_ms is not None)
    expected = sum(phase.requested for phase in phases)
    passed = sum(not row.errors for row in rows)
    technical = sum(any(error.startswith("technical:") for error in row.errors) for row in rows)
    costs = [row.cost_usd for row in rows if row.cost_usd is not None]
    incomplete_cost = sum(row.cost_is_partial or row.cost_usd is None for row in rows)
    missing = expected - len(rows)
    return {
        "requested": expected,
        "reported": len(rows),
        "missing": missing,
        "passed": passed,
        "quality_failures": len(rows) - passed - technical,
        "technical_failures": technical,
        "pass_rate": passed / expected,
        "cost_usd_known": str(sum(costs, Decimal(0))) if costs else None,
        "cost_incomplete_cases": incomplete_cost,
        "cost_complete": not missing and not incomplete_cost,
        "wall_seconds": round(sum(phase.wall_seconds for phase in phases), 3),
        "case_p50_ms": median(durations) if durations else None,
        "case_p95_ms": durations[math.ceil(0.95 * len(durations)) - 1] if durations else None,
    }


def run_phase(
    out: Path,
    model: str,
    phase: str,
    arguments: list[str],
    expected: int | tuple[str, ...],
) -> Phase:
    stem = f"{model.split('/', 1)[1]}-{phase}"
    receipts = out / f"{stem}.jsonl"
    log = out / f"{stem}.log"
    print(f"{model} · {phase} · see {log.name}", file=sys.stderr, flush=True)
    started = perf_counter()
    child_env = os.environ.copy()
    child_env["PYDANTIC_AI_NO_BANNER"] = "1"
    if phase != "extraction":
        # The AgenticOS profiles use their vault key and never need the host's SDK key.
        child_env.pop("OPENROUTER_API_KEY", None)
    with (
        receipts.open("x", encoding="utf-8") as output,
        log.open("x", encoding="utf-8") as diagnostics,
    ):
        process = subprocess.run(  # noqa: S603
            [sys.executable, str(PERSONAL), *arguments],
            cwd=ROOT / "backend",
            env=child_env,
            stdout=output,
            stderr=diagnostics,
            check=False,
        )
    elapsed = perf_counter() - started
    rows = [Receipt.model_validate_json(line) for line in receipts.read_text().splitlines() if line]
    ids = [row.case for row in rows]
    count = expected if isinstance(expected, int) else len(expected)
    if (
        any(row.model != model for row in rows)
        or len(set(ids)) != len(ids)
        or len(ids) > count
        or (not isinstance(expected, int) and not set(ids).issubset(expected))
    ):
        raise ValueError(f"{receipts.name} contains receipts outside the requested arm.")
    return Phase(phase, count, rows, elapsed, process.returncode, receipts.name)


def phase_summary(phase: Phase) -> dict[str, object]:
    return {
        **summarize([phase]),
        "exit_code": phase.exit_code,
        "receipts": phase.receipts_file,
        "reason": phase.reason,
        "cases": [
            {
                "id": row.case,
                "errors": row.errors,
                "latency_ms": row.latency_ms,
                "cost_usd": str(row.cost_usd) if row.cost_usd is not None else None,
                "cost_is_partial": row.cost_is_partial,
            }
            for row in phase.receipts
        ],
    }


def agent_phases(args: argparse.Namespace, model: str, profile: UUID) -> list[Phase]:
    base = [
        "--suite",
        "agenticos",
        "--organization-id",
        str(args.organization_id),
        "--user-id",
        str(args.user_id),
        "--model-profile",
        str(profile),
    ]
    case_arguments = [value for case in TOOLS for value in ("--case", case)]
    trace = run_phase(
        args.out,
        model,
        "tool-traces",
        [*base, *case_arguments, "--max-usd", str(args.agent_max_usd)],
        TOOLS,
    )
    costs = [row.cost_usd for row in trace.receipts]
    if len(costs) != len(TOOLS) or any(
        row.cost_is_partial or row.cost_usd is None for row in trace.receipts
    ):
        return [
            trace,
            Phase("persisted-tools", len(LIVE), [], 0, None, None, "Incomplete trace accounting."),
        ]
    remaining = args.agent_max_usd - sum((cost or Decimal(0) for cost in costs), Decimal(0))
    if remaining <= 0:
        return [
            trace,
            Phase("persisted-tools", len(LIVE), [], 0, None, None, "Agent budget exhausted."),
        ]
    live = run_phase(
        args.out,
        model,
        "persisted-tools",
        [*base, "--live-memory", "--max-usd", str(remaining)],
        LIVE,
    )
    return [trace, live]


def compare(args: argparse.Namespace) -> int:
    sha = subprocess.check_output(
        ["/usr/bin/env", "git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    summaries: dict[str, object] = {}
    report: dict[str, object] = {
        "git_sha": sha,
        "agent_max_usd_per_model": str(args.agent_max_usd),
        "maintenance_stop_usd_per_model": str(args.maintenance_max_usd),
        "models": summaries,
    }
    path = args.out / "summary.json"
    failed = False
    for model, profile in (
        (HAIKU, None),
        (LUNA, None),
        (SONNET, args.sonnet_profile),
        (SOL, args.sol_profile),
    ):
        if profile is None:
            phases = [
                run_phase(
                    args.out,
                    model,
                    "extraction",
                    [
                        "--suite",
                        "memory",
                        "--model",
                        model,
                        "--limit",
                        "53",
                        "--max-usd",
                        str(args.maintenance_max_usd),
                    ],
                    53,
                )
            ]
        else:
            phases = agent_phases(args, model, profile)
        summaries[model] = {
            **summarize(phases),
            "phases": {phase.name: phase_summary(phase) for phase in phases},
        }
        failed |= any(
            phase.exit_code != 0 or len(phase.receipts) != phase.requested for phase in phases
        )
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(path)
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, required=True, help="New directory for raw receipts, logs and summary."
    )
    parser.add_argument("--organization-id", type=UUID, required=True)
    parser.add_argument("--user-id", type=UUID, required=True)
    parser.add_argument("--sonnet-profile", type=UUID, required=True)
    parser.add_argument("--sol-profile", type=UUID, required=True)
    parser.add_argument("--agent-max-usd", type=Decimal, default=Decimal("5"))
    parser.add_argument("--maintenance-max-usd", type=Decimal, default=Decimal("0.25"))
    args = parser.parse_args()
    if not os.environ.get("OPENROUTER_API_KEY"):
        parser.error("Set OPENROUTER_API_KEY in the environment for maintenance.")
    if os.environ.get("AGENTICOS_PERSONAL_EVAL") != "1":
        parser.error("Set AGENTICOS_PERSONAL_EVAL=1 for the disposable eval stack.")
    if args.sonnet_profile == args.sol_profile:
        parser.error("Sonnet and Sol need distinct model profiles.")
    if any(
        not amount.is_finite() or amount <= 0
        for amount in (args.agent_max_usd, args.maintenance_max_usd)
    ):
        parser.error("Spend limits must be finite and positive.")
    return compare(args)


if __name__ == "__main__":
    raise SystemExit(main())
