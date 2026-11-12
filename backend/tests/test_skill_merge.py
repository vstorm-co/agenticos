"""The three-way merge a fork's catch-up and its move to main start from.

Pure functions over text, so each case is the three texts and what comes out.
"""

import time

import pytest

from app.services.skill_merge import (
    MAX_LINES,
    MAX_REPEATS,
    FileMerge,
    MergePart,
    MergeTooLarge,
    PartState,
    merge_files,
    merge_text,
    merge_value,
    merged_text,
)

BASE = "# Refunds\nAsk for the order id.\nCheck the date.\nOffer a refund.\nSay thanks.\n"


def _states(parts: list[MergePart]) -> list[PartState]:
    return [part.state for part in parts]


class TestMergeText:
    def test_changes_to_different_parts_merge_by_themselves(self):
        fork = BASE.replace("Ask for the order id.", "Ask for the order id and the email.")
        main = BASE.replace("Say thanks.", "Say thanks and close the ticket.")

        parts = merge_text(BASE, fork, main)

        assert PartState.CONFLICT not in _states(parts)
        assert merged_text(parts) == (
            "# Refunds\nAsk for the order id and the email.\nCheck the date.\n"
            "Offer a refund.\nSay thanks and close the ticket.\n"
        )

    def test_the_same_part_changed_differently_is_a_conflict_with_each_sides_text(self):
        fork = BASE.replace("Offer a refund.", "Offer store credit.")
        main = BASE.replace("Offer a refund.", "Offer a refund within 30 days.")

        parts = merge_text(BASE, fork, main)

        [conflict] = [part for part in parts if part.state is PartState.CONFLICT]
        assert (conflict.base, conflict.fork, conflict.main) == (
            "Offer a refund.\n",
            "Offer store credit.\n",
            "Offer a refund within 30 days.\n",
        )
        assert conflict.merged is None
        assert merged_text(parts) is None

    def test_the_same_change_on_both_sides_is_taken_once(self):
        both = BASE.replace("Check the date.", "Check the date on the receipt.")

        parts = merge_text(BASE, both, both)

        assert PartState.BOTH in _states(parts)
        assert merged_text(parts) == both

    def test_a_line_one_side_deleted_and_the_other_kept_is_deleted(self):
        main = BASE.replace("Check the date.\n", "")

        parts = merge_text(BASE, BASE, main)

        [deleted] = [part for part in parts if part.state is PartState.MAIN]
        assert (deleted.base, deleted.main) == ("Check the date.\n", "")
        assert merged_text(parts) == main

    def test_a_line_one_side_deleted_and_the_other_changed_is_a_conflict(self):
        fork = BASE.replace("Check the date.\n", "")
        main = BASE.replace("Check the date.", "Check the date and the amount.")

        assert PartState.CONFLICT in _states(merge_text(BASE, fork, main))

    def test_edits_on_neighbouring_lines_are_one_conflict_and_a_line_apart_merge(self):
        fork = BASE.replace("Ask for the order id.", "Ask for the id.")
        next_line = BASE.replace("Check the date.", "Check when it was bought.")
        line_apart = BASE.replace("Offer a refund.", "Refund it.")

        assert _states(merge_text(BASE, fork, next_line)).count(PartState.CONFLICT) == 1
        assert merged_text(merge_text(BASE, fork, line_apart)) == fork.replace(
            "Offer a refund.", "Refund it."
        )

    def test_text_added_at_the_end_by_one_side_is_kept_and_by_both_differently_conflicts(self):
        fork = BASE + "Log it.\n"
        main = BASE + "Tell the manager.\n"

        assert merged_text(merge_text(BASE, fork, BASE)) == fork
        assert _states(merge_text(BASE, fork, main))[-1] is PartState.CONFLICT

    def test_from_an_empty_base_each_side_is_taken_alone_or_conflicts(self):
        assert merged_text(merge_text("", "Fork text.\n", "")) == "Fork text.\n"
        assert _states(merge_text("", "Same.\n", "Same.\n")) == [PartState.BOTH]
        assert _states(merge_text("", "Fork.\n", "Main.\n")) == [PartState.CONFLICT]
        assert merge_text("", "", "") == []
        assert merged_text([]) == ""

    def test_a_blank_line_one_side_dropped_stays_dropped_beside_the_others_edit(self):
        base = "# Refunds\n\n\nOffer a refund.\nSay thanks.\n"
        fork = "# Refunds\n\nOffer a refund.\nSay thanks.\n"
        main = base.replace("Say thanks.", "Say thank you.")

        parts = merge_text(base, fork, main)

        assert PartState.CONFLICT not in _states(parts)
        assert merged_text(parts) == "# Refunds\n\nOffer a refund.\nSay thank you.\n"

    def test_nothing_changed_is_one_unchanged_part(self):
        parts = merge_text(BASE, BASE, BASE)

        assert _states(parts) == [PartState.SAME]
        assert merged_text(parts) == BASE

    def test_line_endings_alone_change_nothing_and_the_merge_is_lf(self):
        crlf = BASE.replace("\n", "\r\n")
        fork = crlf.replace("Say thanks.", "Say thank you.")
        old_mac = BASE.replace("Ask for the order id.", "Ask for the id.").replace("\n", "\r")

        parts = merge_text(crlf, fork, old_mac)

        assert PartState.CONFLICT not in _states(parts)
        assert merged_text(parts) == BASE.replace(
            "Ask for the order id.", "Ask for the id."
        ).replace("Say thanks.", "Say thank you.")

    def test_a_trailing_newline_is_a_change_of_the_last_line(self):
        base = "One.\nTwo.\nThree."
        fork = "One.\nTwo.\nThree.\n"
        main = "Uno.\nTwo.\nThree."

        assert merged_text(merge_text(base, fork, main)) == "Uno.\nTwo.\nThree.\n"
        assert _states(merge_text(base, fork, "One.\nTwo.\nTres.")) == [
            PartState.SAME,
            PartState.CONFLICT,
        ]


@pytest.mark.security
class TestWhatIsTooLargeToMerge:
    """Matching goes over every pair of equal lines once per stretch it splits the texts
    into, so repetition is what costs. A repeated line never anchors it, which keeps a body
    an editor wrote from holding a worker's CPU; only a side past the line limit is refused."""

    def test_a_side_past_the_line_limit_is_refused(self):
        long = "".join(f"line {number}\n" for number in range(MAX_LINES + 1))

        with pytest.raises(MergeTooLarge, match=f"more than {MAX_LINES} lines"):
            merge_text("one\n", "one\n", long)

    def test_a_long_body_of_distinct_lines_still_merges(self):
        distinct = "".join(f"line {number}\n" for number in range(MAX_LINES))
        changed = distinct.replace("line 7\n", "LINE 7\n")
        assert merged_text(merge_text(distinct, changed, distinct)) == changed

    def test_a_line_repeated_past_the_anchor_limit_still_merges(self):
        repeated = "Check the date.\n" * (MAX_REPEATS * 300)

        parts = merge_text(repeated, repeated + "fork\n", "main\n" + repeated)

        assert merged_text(parts) == "main\n" + repeated + "fork\n"

    def test_steps_between_repeated_rules_merge_at_once_one_conflict_each(self):
        """`---` and `- [ ]` repeat as blank lines do; matched like other lines, nine hundred
        rewritten steps between them held the CPU for a minute under the old pair limit."""

        def steps(side: str) -> str:
            return "".join(
                f"## Step {number} as {side} has it\n---\n- [ ]\n" for number in range(900)
            )

        started = time.perf_counter()
        parts = merge_text(steps("base"), steps("fork"), steps("main"))
        took = time.perf_counter() - started

        assert took < 2
        assert _states(parts) == [PartState.CONFLICT, PartState.SAME] * 900
        assert {part.base for part in parts if part.state is PartState.SAME} == {"---\n- [ ]\n"}

    def test_paragraphs_between_blank_lines_merge_at_once_one_conflict_each(self):
        """Blank lines repeat in every skill; matched like other lines, a thousand rewritten
        paragraphs held the CPU for a minute. Paired in order, each paragraph is still
        its own conflict, between the blank lines both sides kept."""

        def paragraphs(side: str) -> str:
            return "".join(f"Paragraph {number} as {side} has it.\n\n" for number in range(1000))

        started = time.perf_counter()
        parts = merge_text(paragraphs("base"), paragraphs("fork"), paragraphs("main"))
        took = time.perf_counter() - started

        assert took < 2
        assert _states(parts) == [PartState.CONFLICT, PartState.SAME] * 1000
        assert {part.base for part in parts if part.state is PartState.SAME} == {"\n"}

    def test_a_blank_line_one_side_adds_between_paragraphs_is_its_change(self):
        base = "One.\n\nTwo.\n"
        fork = "One.\n\n\nTwo.\n"
        main = "One!\n\nTwo.\n"

        assert merged_text(merge_text(base, fork, main)) == "One!\n\n\nTwo.\n"


class TestMergeValue:
    @pytest.mark.parametrize(
        ("fork", "main", "state", "merged"),
        [
            ("Refunds.", "Refunds.", PartState.SAME, "Refunds."),
            ("Refunds and returns.", "Refunds.", PartState.FORK, "Refunds and returns."),
            ("Refunds.", "Refunds, in 30 days.", PartState.MAIN, "Refunds, in 30 days."),
            ("Returns.", "Returns.", PartState.BOTH, "Returns."),
            ("Returns.", "Credit.", PartState.CONFLICT, None),
        ],
    )
    def test_a_description_is_merged_whole(self, fork, main, state, merged):
        part = merge_value("Refunds.", fork, main)

        assert (part.state, part.merged) == (state, merged)


class TestMergeFiles:
    def test_each_file_is_merged_by_its_digest_and_listed_by_name(self):
        base = {"faq.md": "a1", "old.md": "o1", "gone.md": "g1", "both.md": "b1"}
        fork = {"faq.md": "a2", "old.md": "o1", "gone.md": "g2", "both.md": "b2", "new.md": "n1"}
        main = {"faq.md": "a1", "both.md": "b2", "main.md": "m1"}

        merged = {file.name: file for file in merge_files(base, fork, main)}

        assert list(merged) == sorted(merged)
        assert merged["faq.md"] == FileMerge("faq.md", PartState.FORK, "a1", "a2", "a1")
        assert (merged["old.md"].state, merged["old.md"].merged) == (PartState.MAIN, None)
        assert merged["gone.md"].state is PartState.CONFLICT
        assert (merged["both.md"].state, merged["both.md"].merged) == (PartState.BOTH, "b2")
        assert (merged["new.md"].merged, merged["main.md"].merged) == ("n1", "m1")

    def test_files_nobody_changed_stay(self):
        [kept] = merge_files({"faq.md": "a1"}, {"faq.md": "a1"}, {"faq.md": "a1"})

        assert (kept.state, kept.merged) == (PartState.SAME, "a1")
