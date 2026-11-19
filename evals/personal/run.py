"""Check the personal assistant corpus, export native datasets, or score a model."""

import argparse
import asyncio
import csv
import json
import os
import sys
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, NamedTuple, TypedDict
from uuid import UUID

import httpx
from pydantic import JsonValue
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

# As in evals/retrieval: use the platform's locked dependencies and schemas.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.schemas.dataset import CaseMessage, DatasetCaseContent, DatasetVersionRead
from app.schemas.eval_run import EvalCaseList, EvalRunEstimate, EvalRunRead, EvalRunRequest
from app.schemas.scoring import ExpectedToolCall
from app.services.dataset_files import parse
from app.services.memory import extraction
from app.services.proactive import _nightly as nightly
from app.services.role_packs import PACKS

ROOT = Path(__file__).resolve().parent
Suite = Literal["memory", "briefing", "agenticos"]
SUITES: tuple[Suite, ...] = ("memory", "briefing", "agenticos")
BASE_DATE = date(2026, 11, 16)


class Scenario(NamedTuple):
    id: str
    suite: Suite
    case: DatasetCaseContent
    state: dict[str, str]
    operation: str
    cue: str
    forbidden: tuple[str, ...] = ()


def settings(text: str) -> dict[str, str]:
    if text == "-":
        return {}
    pairs = {}
    for part in text.split(";"):
        key, value = part.split("=", 1)
        pairs[key] = value
    return pairs


def message(role: Literal["user", "assistant"], content: str) -> CaseMessage:
    return CaseMessage(role=role, content=content)


def tool_name(name: str) -> str:
    if name in {
        "remember",
        "correct_memory",
        "share_memory",
        "write_memory",
        "web_search",
        "search_tools",
    }:
        return name
    return "agenticos_" + name.removeprefix("agenticos_")


def authored_history() -> dict[str, list[CaseMessage]]:
    raw = json.loads((ROOT / "history.json").read_text())
    return {key: [CaseMessage.model_validate(turn) for turn in turns] for key, turns in raw.items()}


def load(suite: Suite) -> list[Scenario]:
    histories = authored_history()
    scenarios = []
    with (ROOT / f"{suite}.tsv").open() as file:
        rows = csv.reader(file, delimiter="|", quoting=csv.QUOTE_NONE)
        for key, *fields in rows:
            if key.startswith("#"):
                continue
            history = histories.get(key, [])
            forbidden: tuple[str, ...] = ()
            kwargs: dict[str, object] = {}
            if suite == "memory":
                first, answer, prompt, existing, operation, cue = fields
                state = settings(existing)
                reference = {
                    "add": f"Extract a supported, durable memory about {cue}, with a direct user quote.",
                    "update": f"Recognize the change to {cue} and reuse the existing memory subject.",
                    "none": "Leave current memory unchanged. The conversation has no new durable claim.",
                }[operation]
            elif suite == "briefing":
                first, answer, second, prompt, stored, operation, cue = fields
                history = [
                    *history,
                    message("user", first),
                    message("assistant", "What should I include?"),
                    message("user", answer),
                    message("assistant", "Understood."),
                ]
                first, answer = second, "I can use the requested source if it is connected."
                state = settings(stored)
                reference = f"Produce {operation} new recurring proposals."
                if cue != "-":
                    reference += f" Ground the proposal in these requests and include {cue}."
            else:
                first, answer, prompt, tools, args, disallowed, reference = fields
                state = {}
                operation = ""
                cue = ""
                forbidden = (
                    tuple(map(tool_name, disallowed.split(","))) if disallowed != "-" else ()
                )
                if tools != "-":
                    kwargs["expected_tool_calls"] = [
                        ExpectedToolCall(
                            tool=tool_name(tool), args=dict[str, JsonValue](settings(args))
                        )
                        for tool in tools.split(",")
                    ]
                if forbidden:
                    kwargs["counter_example"] = "Called a forbidden tool: " + ", ".join(forbidden)
            case = DatasetCaseContent.model_validate(
                {
                    **kwargs,
                    "input": prompt,
                    "history": [*history, message("user", first), message("assistant", answer)],
                    "reference_answer": reference,
                    "tags": [suite, key],
                }
            )
            scenarios.append(Scenario(key, suite, case, state, operation, cue, forbidden))
    return scenarios


def jsonl(scenarios: Iterable[Scenario]) -> str:
    return "".join(item.case.model_dump_json(exclude_none=True) + "\n" for item in scenarios)


def all_turns(case: DatasetCaseContent) -> list[CaseMessage]:
    return [*case.history, message("user", case.input)]


class MemoryInput(TypedDict):
    conversation: list[dict[str, str]]
    existing_memory: list[dict[str, str]]


def memory_input(scenario: Scenario) -> MemoryInput:
    return {
        "conversation": extraction.transcript_for_extraction(
            (turn.role, turn.content)
            for turn in all_turns(scenario.case)[-extraction.MAX_TRANSCRIPT_MESSAGES :]
        ),
        "existing_memory": [
            {"subject": subject, "statement": text} for subject, text in scenario.state.items()
        ],
    }


def briefing_input(scenario: Scenario) -> dict[str, object]:
    state = scenario.state
    # The authored four requests are first ask, correction, next ask and last ask.
    user_turns = [turn for turn in all_turns(scenario.case) if turn.role == "user"]
    request_days = [0, 0, 0, 0] if "same-thread" in state else [0, 0, 1, 2]
    requests = [
        {
            "id": index,
            "thread": f"thread-{day}",
            "date_utc": (BASE_DATE + timedelta(days=day)).isoformat(),
            "text": turn.content[: nightly._CLIP],
        }
        for index, (turn, day) in enumerate(zip(user_turns, request_days, strict=True), 1)
    ]
    return {
        "person": {
            "language": state.get("language", "English"),
            "time_zone": "UTC",
            "role": state.get("role"),
            "work": None,
            "working_hours": None,
        },
        "requests_this_week": requests,
        "current_memory": [
            {"scope": scope, "kind": "fact", "statement": state[key]}
            for key, scope in (("profile-memory", "profile"), ("agent-memory", "starter"))
            if key in state
        ],
        "prior_proposals": [
            {"title": state[status], "status": status, "intent": None, "request": state[status]}
            for status in ("dismissed", "accepted")
            if status in state
        ],
        "notes_about_them": [],
        "their_routines": [state["routine"]] if "routine" in state else [],
        "connected_services": [state["connection"]] if "connection" in state else [],
        "role_packs": [
            {"id": pack.id, "name": pack.name, "description": pack.description} for pack in PACKS
        ],
    }


def memory_errors(scenario: Scenario, found: extraction._Extraction) -> list[str]:
    errors = []
    user_text = [
        turn["text"] for turn in memory_input(scenario)["conversation"] if turn["role"] == "user"
    ]
    if any(not any(claim.evidence in text for text in user_text) for claim in found.claims):
        errors.append("claim without exact user evidence")
    if scenario.operation == "none":
        return errors + (["unexpected claim"] if found.claims else [])
    matching = [
        claim for claim in found.claims if scenario.cue.casefold() in claim.statement.casefold()
    ]
    if len(matching) != 1:
        errors.append("missing expected claim or duplicate claims")
    elif scenario.operation == "update" and matching[0].subject not in scenario.state:
        errors.append("correction did not reuse the existing subject")
    return errors


def briefing_errors(scenario: Scenario, found: nightly.NightlyReading) -> list[str]:
    errors = []
    if len(found.repeats) != int(scenario.operation):
        errors.append("wrong number of recurring proposals")
    if any(scenario.cue.casefold() not in item.prompt.casefold() for item in found.repeats):
        errors.append("proposal not grounded in the expected source or output")
    valid_ids = {1, 3, 4} if "same-thread" not in scenario.state else set()
    if any(set(item.evidence) != valid_ids for item in found.repeats):
        errors.append("invalid evidence for recurrence")
    expected_role = {
        "role-from-claim": "support operations lead",
        "language-profile": "contracts analyst",
    }.get(scenario.id)
    proposed_role = (
        found.profile.job_title.casefold() if found.profile and found.profile.job_title else None
    )
    # Job titles may be localized for the Polish profile fixture.
    if scenario.id == "language-profile" and proposed_role:
        proposed_role = expected_role if "umów" in proposed_role else proposed_role
    if proposed_role != expected_role:
        errors.append("missing or unsupported role proposal")
    if len({nightly._normalized(starter) for starter in found.starters}) != len(found.starters):
        errors.append("duplicate starters")
    if any(len(starter) > nightly.STARTER_CHARS for starter in found.starters):
        errors.append("starter exceeds configured limit")
    return errors


async def run_background(model: str, scenarios: Iterable[Scenario]) -> int:
    memory = Agent(model, instructions=extraction._INSTRUCTIONS, output_type=extraction._Extraction)
    briefing = Agent(model, instructions=nightly._INSTRUCTIONS, output_type=nightly.NightlyReading)
    limit = UsageLimits(request_limit=2, output_tokens_limit=2_000)
    failed = 0
    for item in scenarios:
        if item.suite == "memory":
            result = await memory.run(
                json.dumps(memory_input(item), ensure_ascii=False), usage_limits=limit
            )
            errors = memory_errors(item, result.output)
        else:
            result = await briefing.run(
                json.dumps(briefing_input(item), ensure_ascii=False), usage_limits=limit
            )
            errors = briefing_errors(item, result.output)
        failed += bool(errors)
        usage = result.usage
        print(
            json.dumps(
                {
                    "case": item.id,
                    "errors": errors,
                    "requests": usage.requests,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                }
            ),
            flush=True,
        )
    return int(failed > 0)


def native_report(client: httpx.Client, run_id: UUID) -> int:
    path = f"/eval-runs/{run_id}"
    run = EvalRunRead.model_validate(client.get(path).raise_for_status().json())
    print(json.dumps({"run": str(run.id), "status": run.status, "cost_usd": str(run.cost_usd)}))
    expected = {item.id: item for item in load("agenticos")}
    verdicts = []
    for skip in range(0, run.cases, 100):
        page = EvalCaseList.model_validate(
            client.get(path + "/cases", params={"skip": skip, "limit": 100})
            .raise_for_status()
            .json()
        )
        for case in page.items:
            scenario = next((expected[tag] for tag in case.tags if tag in expected), None)
            if scenario is None:
                continue
            for attempt in case.attempts:
                forbidden = sorted({call.tool for call in attempt.calls} & set(scenario.forbidden))
                passed = not forbidden and attempt.state == "passed"
                verdicts.append(passed)
                print(
                    json.dumps(
                        {
                            "case": scenario.id,
                            "state": attempt.state,
                            "passed": passed,
                            "forbidden_calls": forbidden,
                            "calls": [
                                {"tool": call.tool, "outcome": call.outcome}
                                for call in attempt.calls
                            ],
                            "input_tokens": attempt.input_tokens,
                            "output_tokens": attempt.output_tokens,
                            "cost_usd": str(attempt.cost_usd),
                        }
                    )
                )
    return int(run.status != "completed" or not verdicts or not all(verdicts))


def run_native(args: argparse.Namespace) -> int:
    token = os.getenv("AGENTICOS_EVAL_TOKEN")
    if not token:
        raise SystemExit("Set AGENTICOS_EVAL_TOKEN to a test workspace member access token.")
    headers = {"Authorization": f"Bearer {token}"}
    if args.organization_id is not None:
        headers["X-Organization-Id"] = str(args.organization_id)
    with httpx.Client(
        base_url=args.api_url.rstrip("/") + "/api/v1",
        headers=headers,
        timeout=30,
    ) as client:
        if args.report_run is not None:
            return native_report(client, args.report_run)
        if args.import_into is not None:
            payload = jsonl(load(args.suite)).encode()
            response = client.post(
                f"/datasets/{args.import_into}/import",
                files={"file": (f"{args.suite}.jsonl", payload, "application/jsonl")},
            ).raise_for_status()
            version = DatasetVersionRead.model_validate(response.json())
            print(version.model_dump_json())
            return 0
        request = EvalRunRequest(
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            environment_id=args.environment_id,
            reruns=0,
        ).model_dump(mode="json", exclude_none=True)
        path = f"/agents/{args.agent_id}/eval-runs"
        estimate = EvalRunEstimate.model_validate(
            client.post(path + "/estimate", json=request).raise_for_status().json()
        )
        print(estimate.model_dump_json(), flush=True)
        if args.max_usd is None:
            return 0
        if not estimate.affordable or estimate.total_usd > args.max_usd or estimate.ungraded_cases:
            raise SystemExit("Estimate is over budget or includes ungraded cases.")
        result = client.post(path, json=request).raise_for_status().json()
        print(json.dumps({"eval_run_id": result["id"], "status": result["status"]}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=SUITES)
    parser.add_argument(
        "--export", type=Path, help="Write native JSONL datasets to this directory."
    )
    parser.add_argument(
        "--model", help="Run a paid production-prompt replay for one background suite."
    )
    parser.add_argument("--limit", type=int, help="Required upper bound on paid background cases.")
    parser.add_argument("--case", action="append", help="Select case IDs in a background replay.")
    parser.add_argument(
        "--api-url", help="Estimate or submit an imported dataset via the platform eval API."
    )
    parser.add_argument("--organization-id", type=UUID)
    parser.add_argument("--dataset-id", type=UUID)
    parser.add_argument("--dataset-version", type=int)
    parser.add_argument("--environment-id", type=UUID)
    parser.add_argument("--agent-id", type=UUID)
    parser.add_argument(
        "--import-into", type=UUID, help="Append the selected suite to an existing test dataset."
    )
    parser.add_argument(
        "--report-run", type=UUID, help="Score tool traces from a native AgenticOS eval."
    )
    parser.add_argument(
        "--max-usd", type=Decimal, help="Passing a positive amount submits the native run."
    )
    args = parser.parse_args()
    if args.api_url:
        if args.import_into is not None and args.suite is None:
            parser.error("--import-into requires --suite")
        if (
            args.report_run is None
            and args.import_into is None
            and (args.agent_id is None or args.dataset_id is None or args.dataset_version is None)
        ):
            parser.error("--api-url requires --agent-id, --dataset-id and --dataset-version")
        if args.max_usd is not None and (not args.max_usd.is_finite() or args.max_usd <= 0):
            parser.error("--max-usd must be finite and positive")
        return run_native(args)
    scenarios = []
    for suite in (args.suite,) if args.suite else SUITES:
        items = load(suite)
        output = jsonl(items)
        if len(parse(output.encode(), "jsonl")) != len(items):
            raise SystemExit(f"{suite}: export dropped cases")
        for item in items:
            if suite == "memory":
                memory_input(item)
            elif suite == "briefing":
                briefing_input(item)
        if args.export:
            args.export.mkdir(parents=True, exist_ok=True)
            (args.export / f"{suite}.jsonl").write_text(output)
        print(f"{suite}: {len(items)} cases", file=sys.stderr)
        scenarios.extend(items)
    ids = [item.id for item in scenarios]
    if len(ids) != len(set(ids)):
        raise SystemExit("Duplicate case IDs")
    if args.model:
        if args.suite not in ("memory", "briefing") or args.limit is None or args.limit < 1:
            parser.error("--model requires --suite memory/briefing and a positive --limit")
        if args.case:
            if missing := set(args.case) - set(ids):
                parser.error(f"Unknown cases: {', '.join(sorted(missing))}")
            scenarios = [item for item in scenarios if item.id in args.case]
        return asyncio.run(run_background(args.model, scenarios[: args.limit]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
