"""The parity table in `docs/channels.md`, asserted rather than trusted.

Three surfaces run the same agent through the same runner and do not offer the
same run. Several of the differences are decisions and several were accidents,
and nothing said which (#936). The table says now - and a table nothing checks
is a table that describes what the code used to do.

The shape is `test_capability_registry.py::TestFrontendToolCatalog`'s: two lists
that have to agree, compared here so a change to one without the other fails.
What is compared is what each surface *passes into the runner*, which is where a
surface's offer actually lives.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.schemas.agent import AgentRunRequest, AgentRunResult
from app.services import embed_session
from app.services.agent_runner import AgentRunnerService

CHANNELS = Path(__file__).resolve().parents[2] / "docs" / "channels.md"


@pytest.fixture(scope="module")
def table() -> str:
    """The parity section, which is what the rows below are read from."""
    text = CHANNELS.read_text()
    start = text.index("## What each surface offers, and why the differences are differences")
    return text[start : text.index("\n## ", start + 1)]


class TestTheAccidentalGapsAreClosed:
    """The five the issue named, and the two that were genuinely accidents."""

    def test_the_api_can_attach_a_file(self) -> None:
        """The surface whose whole purpose is "run it from your own backend" was
        the one that could not send a document - `execute` has taken attachments
        since the widget grew them."""
        assert "file_ids" in AgentRunRequest.model_fields

    def test_the_api_says_what_a_parked_run_is_waiting_on(self) -> None:
        """The field existed and the route never filled it, so a caller whose run
        parked got an empty string, a status, and nothing to act on."""
        assert "parked" in AgentRunResult.model_fields
        source = inspect.getsource(
            __import__("app.api.routes.v1.agents", fromlist=["run_agent"]).run_agent
        )
        assert "parked_calls" in source

    def test_a_streaming_surface_can_be_told_a_summary_is_running(self) -> None:
        """`CompactionSink`'s docstring names the failure it was written for -
        "the chat simply stopped for the length of it with nothing said" - and
        the socket had exactly that, because only `/chat` passed a sink."""
        for method in (AgentRunnerService.prepare, AgentRunnerService.execute):
            assert "on_compaction" in inspect.signature(method).parameters

    def test_the_socket_passes_one(self) -> None:
        assert "on_compaction=self._compaction_event" in inspect.getsource(embed_session)

    def test_a_compaction_frame_is_not_behind_an_operator_switch(self) -> None:
        """What they carry is that the agent is tidying its own notes, which is a
        fact about the product rather than about its reasoning or what it
        searched for - so a page showing neither still gets them."""
        always = embed_session._ALWAYS
        assert {"compaction_started", "compaction_finished", "compaction_impossible"} <= always


class TestTheTableSaysWhatTheCodeDoes:
    def test_every_row_of_the_table_carries_a_reason_for_every_no(self, table: str) -> None:
        """The whole point of the audit: a difference somebody can point at. A
        bare "no" is the state this issue existed to end."""
        rows = [line for line in table.splitlines() if line.startswith("| ") and "---" not in line]
        assert len(rows) > 5, "the parity table has gone missing from docs/channels.md"
        for row in rows[1:]:
            for cell in (part.strip() for part in row.strip("|").split("|")[1:]):
                bare = cell.replace("*", "").strip().rstrip(".").lower()
                if bare.startswith("no") and bare in {"no", "not yet", "no, deliberately"}:
                    pytest.fail(f"a bare 'no' with no reason beside it: {row}")

    def test_it_names_the_three_surfaces(self, table: str) -> None:
        assert "`/chat` (dashboard)" in table
        assert "Raw WebSocket" in table
        assert "The public API" in table

    def test_the_declined_ones_each_have_a_section(self, table: str) -> None:
        """Declining is a legitimate answer and an unexplained decline is not."""
        assert "### `environment_id` on the socket" in table
        assert "### `ask_user` on the socket" in table
        assert "### Approvals on the socket" in table

    def test_the_socket_still_declines_the_environment(self) -> None:
        """Held in code as well as in prose: a frame that chose the environment
        would let a visitor pick which version of the agent answers them."""
        source = inspect.getsource(embed_session)
        assert "environment_id=" not in source

    def test_the_socket_still_declines_a_model_override(self) -> None:
        source = inspect.getsource(embed_session)
        assert "model_profile_id=" not in source

    def test_the_history_frame_is_not_documented_as_hosted_page_only(self) -> None:
        """`continuity_key` and `_ALWAYS` both contradicted that line, so any
        socket with a visitor key gets it."""
        assert "On a hosted page only" not in CHANNELS.read_text()
