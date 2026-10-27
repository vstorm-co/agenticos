"""What the Architect is told about Improve, read as a conversation it has to get right.

There is no eval of the Architect's behaviour, so each scenario a person ran into
is held here as the instruction that answers it: asked why an improvement did not
help, it diagnoses with its tools instead of asking for an id or restating the
numbers, and it promises nothing it cannot do.
"""

import pytest

from app.services import agent_templates
from app.services.assistant import TEMPLATE_KEY


@pytest.fixture(scope="module")
def instructions() -> str:
    template = agent_templates.get(TEMPLATE_KEY)
    assert template is not None
    return template.instructions


def _bullet(instructions: str, lead: str) -> str:
    [line] = [line for line in instructions.splitlines() if line.startswith(f"- **{lead}")]
    return line


def test_a_session_found_earlier_is_reused_and_a_miss_is_looked_up_not_asked(
    instructions: str,
) -> None:
    """Asked a turn later "why didn't it improve?", it once answered "agent not found - give
    me the agent's id", about the agent it had just read."""
    rule = _bullet(instructions, "Keep what you already found")
    assert "`get_improvement` needs only the session id" in rule
    assert "`list_agents`, then `list_improvements`" in rule
    assert "never ask the person for an id" in rule


def test_it_never_promises_to_come_back(instructions: str) -> None:
    """It said "I'll let you know when it's ready"; it only ever answers a message."""
    rule = _bullet(instructions, "You cannot follow up later")
    assert 'never say "I\'ll let you know"' in rule
    assert "notification" in rule
    assert "link the wizard" in rule


def test_why_it_did_not_improve_is_a_diagnosis_from_the_session_and_its_check(
    instructions: str,
) -> None:
    rule = _bullet(instructions, '"Why didn\'t it improve?" needs a diagnosis')
    assert "`get_improvement`" in rule
    assert "`measurement_noise`" in rule
    assert "`get_eval_run`" in rule
    assert "grader's reason" in rule


def test_a_noisy_test_is_named_and_answered_with_a_better_test_not_another_try(
    instructions: str,
) -> None:
    rule = _bullet(instructions, "A noisy test proves nothing")
    assert "`measurement_noise.noisy`" in rule
    assert "do not suggest trying again" in rule
    for remedy in ("yes/no criteria", "fixed check", "more held-out questions", "stronger grader"):
        assert remedy in rule


def test_it_offers_only_what_the_session_and_its_topics_allow(instructions: str) -> None:
    """It offered to review drafts for topics already added to the knowledge base."""
    rule = _bullet(instructions, "Offer only what the data allows")
    assert "draft_ready" in rule
    assert "the next step only while a session is waiting" in rule
    assert "stopping only while a step is running" in rule
    assert "nothing on a closed session" in rule


def test_a_session_is_led_step_by_step_and_never_said_to_run_on_its_own(
    instructions: str,
) -> None:
    """The pipeline stops after Understand, after Changes and at the result."""
    rule = _bullet(instructions, "Step by step")
    assert "`estimate_next_improvement_step`" in rule
    assert 'only on "Next step"' in rule
    assert "continued from the console" in rule
    assert "longer than two hours they finish it with Next step" in rule
    assert "runs on its own" not in instructions
    assert "end it and start a new one" in _bullet(instructions, "Starting")


def test_attempts_compare_by_their_change_not_their_pass_rates(instructions: str) -> None:
    rule = _bullet(instructions, "Explaining a result")
    assert "compare attempts by their change" in rule
    assert "never by pass rates" in rule


def test_the_start_quote_is_the_analysis_not_the_whole_session(instructions: str) -> None:
    """A session's start is priced only up to its first stop; later steps are priced as taken."""
    rule = _bullet(instructions, "Starting")
    assert "Never call `total_usd` the price of the whole session" in rule
    assert "`per_round_usd`" in rule
    assert "spending limit for the whole session - theirs, or `limit_usd`" in rule


def test_every_stop_is_answered_with_the_finding_the_price_and_a_question(
    instructions: str,
) -> None:
    """At a stop it once asked in prose, without the price or what Understand found."""
    rule = _bullet(instructions, "Step by step")
    assert "three parts, all of them, every time" in rule
    assert "with numbers - after Understand from `found`" in rule
    assert "`waiting_for` and its `price`" in rule
    assert '`ask_user_question`: "Next step" first, then "Show the changes"' in rule
    assert '"End"' in rule


def test_how_improving_stands_is_told_from_the_newest_session_and_the_live_version(
    instructions: str,
) -> None:
    """It once filed the newest, outdated session under history and called an older
    session's v7 the live version, after a v8 was published by hand."""
    rule = _bullet(instructions, "How improving stands is the newest session")
    assert "always `get_improvement` on the item marked `newest`" in rule
    assert "a stale or rejected one included" in rule
    assert "mention them only when asked" in rule
    assert "`current_published_version`" in rule
    assert "never call it live" in rule
    assert "`why_stale`" in _bullet(instructions, "A closed session is a record")


def test_what_can_be_done_now_is_read_from_next_actions_and_offered_as_them(
    instructions: str,
) -> None:
    """It said a session stopped after a regression could not be continued, at attempt 1 of
    3 with budget left, without naming the live version and without asking with options."""
    rule = _bullet(instructions, "How improving stands is the newest session")
    assert "Always name the live version from `live_version`" in rule
    assert "never say a session cannot be continued" in rule
    assert "while `next_actions` holds that action" in rule
    assert "`ask_user_question` and its options are exactly `next_actions`" in rule
