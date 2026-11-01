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
    assert "never list them or their links after the newest one" in rule
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


def test_a_session_is_found_without_an_id_never_with_a_made_up_one(instructions: str) -> None:
    """It called list_improvements with an agent id it had invented."""
    rule = _bullet(instructions, "Keep what you already found")
    assert "Never make an id up" in rule
    assert "`list_improvements` with no agent" in rule
    assert "`agent_name`" in rule


def test_a_failed_call_is_never_reported_as_nothing_found(instructions: str) -> None:
    """Its made-up id was refused, and it told the person no session was waiting."""
    rule = _bullet(instructions, "A failed call is not an empty result")
    assert "never say there is nothing, none or no session" in rule
    assert "try again" in rule
    assert 'Say "none" only when a call succeeded and returned no items' in rule


def test_a_repeated_question_about_state_gets_a_fresh_call(instructions: str) -> None:
    """Asked again a stop later, it answered from its own earlier, wrong reply."""
    rule = _bullet(instructions, "Where things stand changes between turns")
    assert "gets a fresh `list_improvements` or `get_improvement` call" in rule
    assert "even when you answered the same question a turn ago" in rule
    assert "Never answer it from an earlier reply" in rule


def test_the_page_is_read_from_its_path_not_its_title(instructions: str) -> None:
    """Asked "what am I looking at?", it answered with the console's generic page title."""
    section = instructions.split("# Showing where things are", 1)[1]
    assert "its path tells you what they are looking at" in section
    assert "never repeat it" in section
    assert "`/agents/<agent id>/improve/<session id>` is that Improve session" in section
    assert "`get_improvement` with the session id" in section


def test_the_wizard_s_words_are_used_never_stored_names_or_error_codes(
    instructions: str,
) -> None:
    """It said a session was at stage "filtering" and quoted "400 BAD_REQUEST"."""
    rule = _bullet(instructions, "Speak the wizard's words, never the system's")
    assert "by its `step`" in rule
    assert "`why_stopped` or `why_stale`" in rule
    for internal in ("filtering", "BAD_REQUEST", "NOT_FOUND"):
        assert internal in rule
    assert "not enough kept-aside questions" in rule


def test_a_reply_starts_from_the_summary_and_keeps_its_warning(instructions: str) -> None:
    """It left out the live version and that the kept attempt broke a question, and listed
    the options in prose."""
    rule = _bullet(instructions, "Start from `summary`")
    assert "keep every fact in it" in rule
    assert "a warning that an attempt makes the agent worse" in rule
    assert (
        "calling `ask_user_question` with the session's `ask` exactly as the tool gave it" in rule
    )


def test_a_price_is_said_as_likely_and_at_most_never_the_most_as_about(instructions: str) -> None:
    """It gave the most a step may cost, $0.32, as "about", where the wizard said about $0.05."""
    rule = _bullet(instructions, "Step by step")
    assert "`expected_usd` is the likely cost and `total_usd` only the most" in rule
    assert 'never say "about" of the most' in rule


def test_an_attempt_is_chosen_only_when_a_person_chose_it_and_old_sessions_stay_apart(
    instructions: str,
) -> None:
    """It called an attempt "the one kept" before anyone chose, and mixed an ended session's
    rejected attempt into the newest session's state."""
    assert "only when the summary says a person chose it" in _bullet(
        instructions, "Explaining a result"
    )
    assert "never mix what an earlier session decided into the newest one's state" in _bullet(
        instructions, "How improving stands is the newest session"
    )


def test_the_closing_question_is_a_tool_call_with_a_worked_example(instructions: str) -> None:
    """It kept asking what to do next in prose, with the options in a list."""
    rule = _bullet(instructions, "Start from `summary`")
    assert 'ask_user_question(questions=[{"header": "Next"' in rule
    assert "never write those choices as a list or a question in your reply" in rule


def test_older_sessions_are_left_out_unless_the_person_asks(instructions: str) -> None:
    """After the newest session it tacked on a list of older ones with their links."""
    rule = _bullet(instructions, "How improving stands is the newest session")
    assert "never list them or their links after the newest one" in rule
    assert "pass `history=true` only when the person asks about earlier sessions" in rule
