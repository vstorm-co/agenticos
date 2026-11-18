"""Deterministic smoke verdicts over model answers and recorded mock-tool calls.

These deliberately narrow assertions are regression signals, not a judge of all
answer quality. Tool execution is fake; native-session isolation has DB/runtime
integration tests. Keep this separate from upstream AgentDojo utility scores.
"""

from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    prompt: str
    required_any: list[str] = []
    forbidden: list[str] = []
    required_calls: list[str] = []
    allowed_calls: list[str] | None = None
    max_calls: int = Field(default=4, ge=0, le=20)
    max_chars: int = Field(default=4000, ge=1)
    coding_sessions: list[tuple[str, str]] = []


class Call(BaseModel):
    name: str
    arguments: dict[str, JsonValue]


class Verdict(BaseModel):
    case_id: str
    passed: bool
    failures: list[str]


def load_cases(path: Path) -> list[Case]:
    cases = TypeAdapter(list[Case]).validate_json(path.read_bytes())
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("Evaluation cases need distinct IDs and at least one case")
    return cases


def evaluate(case: Case, answer: str, calls: list[Call]) -> Verdict:
    failures: list[str] = []
    folded = answer.casefold()
    if case.required_any and not any(word.casefold() in folded for word in case.required_any):
        failures.append("answer lacks the expected evidence")
    # Case-sensitive forbidden strings let a Polish greeting 'siem' coexist with
    # the unwanted acronym 'SIEM'; no language-model judge is hiding this rule.
    if any(word in answer for word in case.forbidden):
        failures.append("answer includes forbidden content")
    if len(answer) > case.max_chars:
        failures.append("answer exceeds the case's length limit")
    if len(calls) > case.max_calls:
        failures.append("too many tool calls")
    names = Counter(call.name for call in calls)
    if Counter(case.required_calls) - names:
        failures.append("missing required tool calls")
    if case.allowed_calls is not None and any(
        call.name not in case.allowed_calls for call in calls
    ):
        failures.append("unexpected tool call")
    if case.coding_sessions:
        sessions = Counter(
            (call.arguments.get("harness"), call.arguments.get("session"))
            for call in calls
            if call.name == "run_coding_agent"
            and isinstance(call.arguments.get("harness"), str)
            and isinstance(call.arguments.get("session"), str)
        )
        if sessions != Counter(case.coding_sessions):
            failures.append("coding sessions did not preserve the requested harness/name")
        if any(call.arguments.get("fresh_session", False) for call in calls):
            failures.append("coding continuation was reset")
    return Verdict(case_id=case.id, passed=not failures, failures=failures)


class CaseResult(BaseModel):
    verdict: Verdict
    answer: str | None = None
    calls: list[Call] = []
    usage: dict[str, int] = {}
