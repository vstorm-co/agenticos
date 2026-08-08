"""What a turn's recorded order has to survive, and what it must not invent.

The timeline exists so a reloaded conversation is the one somebody watched. Every
test here is a way the two could drift apart again.
"""

from app.services.chat_timeline import TurnTimeline


class TestAccumulatingOneTurn:
    def test_consecutive_deltas_of_one_kind_are_one_part(self):
        """A sentence arrives as a dozen frames and is one block on screen. A part
        per frame would be a dozen rows where the client showed one."""
        timeline = TurnTimeline()

        timeline.add_text("Two ")
        timeline.add_text("are ")
        timeline.add_text("open.")

        assert [(part.type, part.text) for part in timeline.parts] == [("text", "Two are open.")]

    def test_the_space_between_two_deltas_is_not_trimmed(self):
        """The parts are accumulated, so trimming each delta deletes the space the
        words meet at. `MessagePart` turns `str_strip_whitespace` off for exactly
        this, and "Two " + "are open." became "Twoare open." without it."""
        timeline = TurnTimeline()

        timeline.add_text("Two ")
        timeline.add_text("are open.")

        assert timeline.text == "Two are open."

    def test_a_tool_closes_the_open_text_part(self):
        """The turn the whole change is about: words, work, then more words. Both
        blocks of text survive and the tool sits between them."""
        timeline = TurnTimeline()

        timeline.add_text("Here are the charts.")
        timeline.add_tool("call-1")
        timeline.add_tool("call-2")
        timeline.add_text("Done - three of them.")

        assert [(part.type, part.text or part.tool_call_id) for part in timeline.parts] == [
            ("text", "Here are the charts."),
            ("tool", "call-1"),
            ("tool", "call-2"),
            ("text", "Done - three of them."),
        ]

    def test_the_stored_text_is_every_block_and_not_only_the_last(self):
        timeline = TurnTimeline()

        timeline.add_text("First. ")
        timeline.add_tool("call-1")
        timeline.add_text("Second.")

        assert timeline.text == "First. Second."

    def test_a_second_block_of_reasoning_is_separated_from_the_first(self):
        """Providers emit a block per thought with no trailing space, so joining
        them ran the last word of one into the first of the next."""
        timeline = TurnTimeline()

        timeline.add_thinking("Counting.")
        timeline.add_thinking("Now checking.")

        assert timeline.thinking == "Counting. Now checking."

    def test_reasoning_and_text_are_read_back_separately(self):
        timeline = TurnTimeline()

        timeline.add_thinking("Deciding what to plot.")
        timeline.add_text("Here it is.")

        assert timeline.thinking == "Deciding what to plot."
        assert timeline.text == "Here it is."

    def test_a_turn_that_never_reasoned_records_no_trace(self):
        """None, not "": the column means "did not reason", and an empty string is
        a reasoning pane somebody can open onto nothing."""
        timeline = TurnTimeline()

        timeline.add_text("Thirty days.")

        assert timeline.thinking is None

    def test_reasoning_resumed_after_a_tool_is_still_one_trace(self):
        timeline = TurnTimeline()

        timeline.add_thinking("Checking the policy.")
        timeline.add_tool("call-1")
        timeline.add_thinking("That settles it.")

        assert timeline.thinking == "Checking the policy. That settles it."


class TestWhatIsWorthStoring:
    def test_a_turn_with_an_order_stores_it(self):
        timeline = TurnTimeline()

        timeline.add_tool("call-1")
        timeline.add_text("Thirty days.")

        stored = timeline.stored()
        assert stored is not None
        assert [part.type for part in stored] == ["tool", "text"]

    def test_a_turn_of_one_part_stores_nothing(self):
        """An ordinary question and answer has no sequence to preserve, and the
        row's own columns already say everything it contained. Writing one would
        put a JSONB array on every plain turn in the deployment to record that the
        answer came after the question."""
        timeline = TurnTimeline()

        timeline.add_text("Thirty days.")

        assert timeline.stored() is None

    def test_a_turn_that_produced_nothing_stores_nothing(self):
        assert TurnTimeline().stored() is None
