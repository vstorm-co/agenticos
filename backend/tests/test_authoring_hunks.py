"""Where a proposed change lands in the draft, and when it refuses to.

A hunk that cannot find its place must say so, never land somewhere else: a
passage that occurs twice, an insertion with nothing to follow, a manual edit
made since. Undo holds to the same rule on what Accept wrote.
"""

from typing import Any

from app.agents.capabilities import ToolOverride
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.db.models.authoring import SpecProposalHunk
from app.schemas.authoring import InstructionChange, Rejection
from app.services import authoring_hunks as hunks

BASE = "Be brief.\nAnswer refunds.\nBe brief.\nHand off to a human."


def _change(old: str = "", new: str = "", after: str = "") -> InstructionChange:
    return InstructionChange(old_text=old, new_text=new, after=after, rationale="because")


def _hunk(**values: Any) -> SpecProposalHunk:
    defaults: dict[str, Any] = {
        "kind": "instructions",
        "status": "pending",
        "old_text": "",
        "new_text": "",
        "context_before": "",
        "context_after": "",
    }
    return SpecProposalHunk(**{**defaults, **values})


def _anchored(base: str, change: InstructionChange, **values: Any) -> SpecProposalHunk:
    columns = hunks.anchor_change(base, change)
    assert not isinstance(columns, Rejection), columns
    return _hunk(**columns, **values)


def _spec(instructions: str = BASE, overrides: dict[str, ToolOverride] | None = None) -> AgentSpec:
    return AgentSpec(
        name="Clerk",
        instructions=instructions,
        capabilities=[
            CapabilityBindingSpec(id="clock"),
            CapabilityBindingSpec(id="knowledge", tool_overrides=overrides or {}),
        ],
    )


class TestAnchoring:
    def test_a_passage_that_occurs_twice_cannot_be_anchored(self):
        assert hunks.anchor_change(BASE, _change("Be brief.", "Be short.")) == (
            Rejection.AMBIGUOUS_ANCHOR
        )

    def test_a_change_that_changes_nothing_is_not_proposed(self):
        assert hunks.anchor_change(BASE, _change("Answer refunds.", "Answer refunds.")) == (
            Rejection.NO_CHANGE
        )
        # Copied loosely, it would still write back what is already there.
        assert hunks.anchor_change(BASE, _change("Answer  refunds.", "Answer refunds.")) == (
            Rejection.NO_CHANGE
        )

    def test_an_insertion_follows_a_unique_passage_or_ends_the_text(self):
        after = hunks.anchor_change(BASE, _change(new="Cite the policy.\n", after="refunds.\n"))
        ended = hunks.anchor_change(BASE, _change(new="\nSign off."))
        ambiguous = hunks.anchor_change(BASE, _change(new="x", after="Be brief."))

        assert isinstance(after, dict) and after["base_start"] == BASE.index("Be brief.\nHand")
        assert isinstance(ended, dict) and ended["base_start"] == len(BASE)
        assert ended["context_after"] == ""
        assert ambiguous == Rejection.AMBIGUOUS_ANCHOR

    def test_a_missing_passage_cannot_be_anchored(self):
        assert hunks.anchor_change(BASE, _change("Never said this.", "x")) == (Rejection.UNANCHORED)
        assert hunks.anchor_change(BASE, _change(new="x", after="Never said this.")) == (
            Rejection.UNANCHORED
        )
        assert hunks.anchor_change(BASE, _change(" \n", "x")) == Rejection.UNANCHORED


class TestCopiedLoosely:
    """A model copies a passage with its quotes straightened, its backticks dropped or
    its lines joined; the change still lands on the draft's own characters, and only
    where that passage occurs once."""

    TEXT = (
        "Before answering, read the `refund-policy` context file.\n"
        "A refund above $500 always needs a manager\u2019s approval \u2014 say so.\n"
        "An item within 30 days qualifies.\n"
        "Store credit applies only within 30 days."
    )

    def test_straightened_quotes_and_dashes_find_the_draft_s_passage(self):
        columns = hunks.anchor_change(
            self.TEXT,
            _change("a manager's approval - say so.", "a manager's approval: log it."),
        )
        assert isinstance(columns, dict)
        assert columns["old_text"] == "a manager\u2019s approval \u2014 say so."
        assert self.TEXT[columns["base_start"] : columns["base_end"]] == columns["old_text"]

    def test_dropped_backticks_and_joined_lines_find_it_too(self):
        columns = hunks.anchor_change(
            self.TEXT,
            _change("read the refund-policy context file. A refund", "read the policy. A refund"),
        )
        assert isinstance(columns, dict)
        assert columns["old_text"] == ("read the `refund-policy` context file.\nA refund")

    def test_an_insertion_follows_a_loosely_copied_passage(self):
        columns = hunks.anchor_change(
            self.TEXT, _change(new=" Log it.", after="a manager's approval - say so.")
        )
        assert isinstance(columns, dict)
        assert columns["base_start"] == self.TEXT.index("\nAn item")
        assert columns["old_text"] == ""

    def test_a_passage_that_occurs_twice_once_evened_out_is_ambiguous(self):
        assert hunks.anchor_change(self.TEXT, _change("within  30\ndays", "within 14 days")) == (
            Rejection.AMBIGUOUS_ANCHOR
        )

    def test_a_passage_is_mentioned_however_loosely_and_however_often(self):
        assert hunks.mentions(self.TEXT, "a manager's approval - say so")
        assert hunks.mentions(self.TEXT, "within 30 days")
        assert not hunks.mentions(self.TEXT, "Refunds over $500 need a manager.")
        assert not hunks.mentions(self.TEXT, "``")

    def test_a_paraphrase_is_still_unanchored(self):
        assert (
            hunks.anchor_change(self.TEXT, _change("Refunds over $500 need a manager.", "x"))
            == Rejection.UNANCHORED
        )


class TestApplying:
    def test_a_duplicated_line_is_replaced_where_it_was_proposed(self):
        hunk = _anchored(BASE, _change("Be brief.\nHand", "Be warm.\nHand"))

        assert hunks.apply_text(BASE, hunk, hunk.new_text) == (
            "Be brief.\nAnswer refunds.\nBe warm.\nHand off to a human."
        )

    def test_a_moved_passage_still_applies_while_it_is_unambiguous(self):
        hunk = _anchored(BASE, _change("Answer refunds.", "Answer refunds and returns."))
        moved = "Hand off to a human.\nAnswer refunds."

        assert hunks.apply_text(moved, hunk, hunk.new_text) == (
            "Hand off to a human.\nAnswer refunds and returns."
        )

    def test_a_passage_edited_away_or_now_ambiguous_is_stale(self):
        hunk = _anchored(BASE, _change("Answer refunds.", "Answer refunds and returns."))

        assert hunks.apply_text("Answer orders.", hunk, hunk.new_text) is None
        assert hunks.apply_text("Answer refunds.\nAnswer refunds.", hunk, hunk.new_text) is None

    def test_an_insertion_lands_only_where_its_surroundings_still_are(self):
        hunk = _anchored(BASE, _change(new="Cite the policy.\n", after="refunds.\n"))

        assert hunks.apply_text(BASE, hunk, hunk.new_text) == (
            "Be brief.\nAnswer refunds.\nCite the policy.\nBe brief.\nHand off to a human."
        )
        assert hunks.apply_text("Answer refunds.", hunk, hunk.new_text) is None

    def test_an_insertion_into_empty_instructions_needs_them_still_empty(self):
        hunk = _anchored("", _change(new="Be kind."))

        assert hunks.apply_text("", hunk, hunk.new_text) == "Be kind."
        assert hunks.apply_text("Somebody wrote this.", hunk, hunk.new_text) is None

    def test_an_insertion_at_the_start_needs_the_text_to_start_the_same(self):
        hunk = _hunk(old_text="", new_text="Hi.\n", context_before="", context_after="Be brief.")

        assert hunks.apply_text(BASE, hunk, hunk.new_text) == "Hi.\n" + BASE
        assert hunks.apply_text("Other.\n" + BASE, hunk, hunk.new_text) is None

    def test_accepting_an_edit_writes_the_persons_text(self):
        hunk = _anchored(BASE, _change("Answer refunds.", "Answer refunds and returns."))

        applied = hunks.apply(_spec(), hunk, text="Answer every refund question.")

        assert applied is not None
        assert "Answer every refund question." in applied.instructions


class TestUndo:
    def test_undo_restores_the_passage_while_the_accepted_text_stands(self):
        hunk = _anchored(BASE, _change("Answer refunds.", "Answer returns."))
        hunk.status = "accepted"
        hunk.accepted_text = "Answer returns."
        accepted = BASE.replace("Answer refunds.", "Answer returns.")

        assert hunks.undo_text(accepted, hunk) == BASE
        assert hunks.applies(_spec(accepted), hunk) is True

    def test_undo_is_stale_once_the_accepted_text_was_edited_by_hand(self):
        hunk = _anchored(BASE, _change("Answer refunds.", "Answer returns."))
        hunk.status = "accepted"
        hunk.accepted_text = "Answer returns."
        edited = BASE.replace("Answer refunds.", "Answer returns, politely.")

        assert hunks.undo_text(edited.replace("returns,", "exchanges,"), hunk) is None
        assert hunks.applies(_spec("Nothing here."), hunk) is False

    def test_an_accepted_deletion_is_undone_by_putting_the_passage_back(self):
        hunk = _anchored(BASE, _change("Answer refunds.\n", ""))
        hunk.status = "accepted"
        hunk.accepted_text = ""

        assert hunks.undo_text(BASE.replace("Answer refunds.\n", ""), hunk) == BASE


def _tool_hunk(**values: Any) -> SpecProposalHunk:
    return _hunk(
        kind="tool_override",
        capability_id="knowledge",
        tool_id="search_knowledge",
        **values,
    )


class TestTools:
    def test_a_description_is_written_over_the_binding_it_was_read_from(self):
        hunk = _tool_hunk(new_description="Search the refund policy first.")

        applied = hunks.apply_tool(_spec(), hunk)

        assert applied is not None
        spec, override = applied
        assert override == {"description": "Search the refund policy first."}
        assert spec.capabilities[1].tool_overrides["search_knowledge"].description == (
            "Search the refund policy first."
        )

    def test_a_rename_keeps_the_description_somebody_already_wrote(self):
        overrides = {"search_knowledge": ToolOverride(description="Mine")}
        hunk = _tool_hunk(base_description="Mine", new_name="find_policy")

        applied = hunks.apply_tool(_spec(overrides=overrides), hunk)

        assert applied is not None
        assert applied[1] == {"name": "find_policy", "description": "Mine"}

    def test_a_newer_manual_edit_or_an_unbound_capability_makes_it_stale(self):
        hunk = _tool_hunk(new_description="Proposed")
        edited = _spec(overrides={"search_knowledge": ToolOverride(description="Mine")})
        unbound = AgentSpec(name="Clerk", instructions=BASE)

        assert hunks.apply_tool(edited, hunk) is None
        assert hunks.apply_tool(unbound, hunk) is None
        assert hunks.apply(unbound, hunk) is None
        assert hunks.applies(edited, hunk) is False

    def test_undo_removes_an_override_the_proposal_created(self):
        hunk = _tool_hunk(new_description="Proposed", status="accepted")
        applied = hunks.apply_tool(_spec(), hunk)
        assert applied is not None
        hunk.accepted_override = applied[1]

        undone = hunks.undo_tool(applied[0], hunk)

        assert undone is not None
        assert "search_knowledge" not in undone.capabilities[1].tool_overrides
        assert hunks.applies(applied[0], hunk) is True

    def test_undo_restores_the_override_the_proposal_replaced(self):
        hunk = _tool_hunk(base_description="Mine", new_description="Proposed", status="accepted")
        hunk.accepted_override = {"description": "Proposed"}
        current = _spec(overrides={"search_knowledge": ToolOverride(description="Proposed")})

        undone = hunks.undo_tool(current, hunk)

        assert undone is not None
        assert undone.capabilities[1].tool_overrides["search_knowledge"].description == "Mine"

    def test_undo_refuses_once_the_override_moved_on(self):
        hunk = _tool_hunk(new_description="Proposed", status="accepted")
        hunk.accepted_override = {"description": "Proposed"}
        moved = _spec(overrides={"search_knowledge": ToolOverride(description="Later")})

        assert hunks.undo_tool(moved, hunk) is None
        assert hunks.undo_tool(AgentSpec(name="Clerk", instructions=""), hunk) is None


class TestProjection:
    def test_every_pending_hunk_is_applied_and_stale_ones_are_left_out(self):
        spec = _spec()
        kept = _anchored(BASE, _change("Answer refunds.", "Answer refunds and returns."))
        tool = _tool_hunk(new_description="Proposed")
        stale = _hunk(old_text="Never written.", new_text="x")
        decided = _anchored(BASE, _change("Hand off to a human.", "Escalate."), status="dismissed")

        projected, skipped = hunks.projection(spec, [kept, tool, stale, decided])

        assert "Answer refunds and returns." in projected.instructions
        assert "Hand off to a human." in projected.instructions
        assert (
            projected.capabilities[1].tool_overrides["search_knowledge"].description == "Proposed"
        )
        assert skipped == [stale]
        assert spec.instructions == BASE

    def test_a_dismissed_hunk_neither_applies_nor_undoes(self):
        hunk = _anchored(BASE, _change("Answer refunds.", "x"), status="dismissed")

        assert hunks.applies(_spec(), hunk) is False


def test_the_tool_catalog_skips_a_capability_the_registry_does_not_know():
    from app.services.authoring_worker import tool_catalog

    spec = AgentSpec(
        name="Clerk",
        instructions="",
        capabilities=[CapabilityBindingSpec(id="retired"), CapabilityBindingSpec(id="charts")],
    )

    assert [row[:2] for row in tool_catalog(spec)] == [("charts", "create_chart")]


def test_verify_reads_an_edit_to_the_tools_beside_one_to_the_instructions():
    """An edit that only reworded a tool is still an edit Verify must be shown."""
    from app.services.authoring_worker import _tool_diff

    published = AgentSpec(
        name="Clerk",
        instructions="",
        capabilities=[CapabilityBindingSpec(id="charts"), CapabilityBindingSpec(id="ask_user")],
    )
    draft = AgentSpec(
        name="Clerk",
        instructions="",
        capabilities=[
            CapabilityBindingSpec(
                id="charts",
                tool_overrides={"create_chart": ToolOverride(description="Only for trends.")},
            ),
            CapabilityBindingSpec(id="artifacts"),
        ],
    )

    lines = _tool_diff(published, draft).splitlines()

    assert "- ask_user / ask_user_question: removed" in lines
    assert "+ artifacts / publish_artifact: added" in lines
    assert any(line.startswith("~ charts / create_chart:") for line in lines)
    assert "  now: create_chart - Only for trends." in lines
    assert _tool_diff(published, published) == ""
