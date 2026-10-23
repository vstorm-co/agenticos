"""What every agent is told about the person it is talking to (#2301).

A person tells the platform their language, time zone, role and what they work
on once, and every agent in every conversation knows it from the first message:
"hej" is answered in Polish because their console is Polish, "every Monday at 9"
is their 9, and an answer is pitched at a head of sales rather than at nobody.

Only for a person the run is really about: a visitor on a public widget is not
the publisher whose account stands in for them, so they get nothing here.
"""

from dataclasses import dataclass

from app.agents.prompt_variables import flattened
from app.agents.spec import AgentSpec
from app.schemas.user import WorkingHours

LANGUAGE_NAMES = {"en": "English", "pl": "Polish", "de": "German"}
"""The console's languages - `ConsoleLocale` - by the name a model reads best."""

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True, slots=True)
class Person:
    """What the account says about the person a run is for."""

    locale: str | None = None
    time_zone: str | None = None
    job_title: str | None = None
    about: str | None = None
    working_hours: WorkingHours | None = None


def _working_days(days: list[int]) -> str:
    """Monday to Friday reads as a range; anything else is listed."""
    if len(days) > 2 and days == list(range(days[0], days[-1] + 1)):
        return f"{_WEEKDAYS[days[0] - 1]} to {_WEEKDAYS[days[-1] - 1]}"
    return ", ".join(_WEEKDAYS[day - 1] for day in days)


def person_briefing(person: Person) -> str | None:
    """The section of the instructions about the person, or None when nothing is known.

    Their role and work are their own words, flattened so they cannot open a
    section or a variable of their own.
    """
    lines: list[str] = []
    if language := LANGUAGE_NAMES.get(person.locale or ""):
        lines.append(
            f"- Their console is in {language}: answer in {language} unless they write "
            "in another language."
        )
    if person.time_zone:
        lines.append(f"- Their time zone is {person.time_zone}; read and state times in it.")
    if person.job_title:
        lines.append(f"- Their role: {flattened(person.job_title)}.")
    if person.about:
        lines.append(f"- What they work on: {flattened(person.about)}")
    if person.working_hours is not None:
        hours = person.working_hours
        lines.append(
            f"- They work {_working_days(hours.days)}, {hours.start}-{hours.end} their time; "
            "plan around it, and nothing waits on it."
        )
    if not lines:
        return None
    return "\n".join(["# The person you are talking to", "", *lines])


def with_person(spec: AgentSpec, person: Person | None) -> AgentSpec:
    """`spec` with the person's section after its own instructions, when there is one."""
    briefing = person_briefing(person) if person is not None else None
    if briefing is None:
        return spec
    instructions = f"{spec.instructions}\n\n{briefing}" if spec.instructions else briefing
    return spec.model_copy(update={"instructions": instructions})
