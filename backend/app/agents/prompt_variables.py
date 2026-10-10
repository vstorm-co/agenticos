"""Variables in an agent's instructions, filled in when each run starts (#2065).

An author writes `Today is {{current_date}}. You are helping {{user_name}}.` and
the run reads the date and the person it is talking to. Two kinds:

- **System variables**, which only the platform knows - the clock, who is
  signed in, the organization, where the conversation happens. Listed in
  :data:`SYSTEM_VARIABLES`, which is also what the Builder offers after `{{`.
- **Custom variables**, defined on the agent itself (`AgentSpec.variables`): a
  name and the text it stands for, so a value used in several places is written
  once and changed once.

Double braces, unlike a channel binding's `{channel_name}`, so JSON, code and set
literals in a prompt are never mistaken for one. A name the agent does not define
is refused at publish (:func:`unknown_variables`), never left for a run to find.

The person's own values are other people's writing - anybody chooses their own
display name - so they are flattened before they reach the instructions: no
braces to open another variable, no line breaks to start a section of their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agents.spec import AgentSpec

VARIABLE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
"""A variable as written in instructions. Lower case, digits and underscores."""

SYSTEM_TIME_ZONE = "system"
PERSON_TIME_ZONE = "user"


@dataclass(frozen=True)
class SystemVariable:
    name: str
    description: str
    """What it becomes, in the words the Builder shows beside it."""
    example: str


SYSTEM_VARIABLES: tuple[SystemVariable, ...] = (
    SystemVariable("current_date", "Today's date when the run starts", "2026-10-10"),
    SystemVariable(
        "current_time", "The time the run starts, with its time zone", "14:05 (Europe/Warsaw)"
    ),
    SystemVariable("weekday", "Today's day of the week", "Saturday"),
    SystemVariable("user_name", "The signed-in person's name, or 'a visitor'", "Ada Lovelace"),
    SystemVariable("user_email", "The signed-in person's email, or empty", "ada@example.com"),
    SystemVariable("organization_name", "The organization the agent runs in", "Acme"),
    SystemVariable(
        "groups", "The groups - departments - the signed-in person is in, or empty", "Finance"
    ),
    SystemVariable("agent_name", "This agent's name", "HR leave"),
    SystemVariable("channel", "Where the conversation happens", "Slack"),
)
"""Every system variable, in the order the Builder lists them."""

SYSTEM_NAMES = frozenset(variable.name for variable in SYSTEM_VARIABLES)

_CHANNELS = {
    "web": "the AgenticOS console",
    "embed": "a chat widget on a website",
    "api": "the API",
    "slack": "Slack",
    "telegram": "Telegram",
    "mattermost": "Mattermost",
    "schedule": "a scheduled run",
}


@dataclass(frozen=True)
class RunFacts:
    """What a run knows that its instructions may name."""

    now: datetime
    user_name: str | None
    user_email: str | None
    organization_name: str | None
    surface: str
    groups: tuple[str, ...] = ()
    """The person's groups in the run's organization (#2072), so one agent can answer
    each department in its own terms."""


def referenced(text: str) -> list[str]:
    """The variable names `text` uses, each once, in order of first use."""
    return list(dict.fromkeys(match.group(1) for match in VARIABLE.finditer(text)))


def unknown_variables(spec: AgentSpec) -> list[str]:
    """Names the instructions use that are neither a system nor a custom variable."""
    defined = SYSTEM_NAMES | {variable.name for variable in spec.variables}
    return [name for name in referenced(spec.instructions) if name not in defined]


def is_time_zone(name: str) -> bool:
    """Whether `name` is an IANA zone this deployment knows."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def time_zone(setting: str, person_zone: str | None) -> ZoneInfo:
    """The zone `{{current_time}}` is told in.

    `user` is the person's own zone when the surface reported one, and the
    deployment's otherwise; an unknown zone name falls back the same way rather
    than failing a run over a clock.
    """
    name = person_zone if setting == PERSON_TIME_ZONE else setting
    if name is None or name == SYSTEM_TIME_ZONE or not is_time_zone(name):
        return ZoneInfo("UTC")
    return ZoneInfo(name)


def _flattened(value: str) -> str:
    """Somebody else's text, unable to open a variable or a section of its own."""
    return " ".join(value.replace("{", "(").replace("}", ")").split())


def _system_values(facts: RunFacts, zone: ZoneInfo, agent_name: str) -> dict[str, str]:
    local = facts.now.astimezone(zone)
    return {
        "current_date": local.date().isoformat(),
        "current_time": f"{local:%H:%M} ({zone.key})",
        "weekday": f"{local:%A}",
        "user_name": _flattened(facts.user_name) if facts.user_name else "a visitor",
        "user_email": _flattened(facts.user_email) if facts.user_email else "",
        "organization_name": _flattened(facts.organization_name or ""),
        "groups": ", ".join(_flattened(name) for name in facts.groups),
        "agent_name": _flattened(agent_name),
        "channel": _CHANNELS.get(facts.surface, facts.surface),
    }


def render(spec: AgentSpec, facts: RunFacts, *, person_zone: str | None = None) -> AgentSpec:
    """The spec with its instructions' variables filled in for this run.

    One pass: a value that itself contains `{{…}}` is not expanded again, so a
    custom variable cannot be made to recurse. A spec that names no variable is
    returned as it is - the common case costs one regex scan.
    """
    if not VARIABLE.search(spec.instructions):
        return spec
    values = {variable.name: variable.value for variable in spec.variables}
    values.update(_system_values(facts, time_zone(spec.time_zone, person_zone), spec.name))

    def fill(match: re.Match[str]) -> str:
        return values.get(match.group(1), match.group(0))

    return spec.model_copy(update={"instructions": VARIABLE.sub(fill, spec.instructions)})
