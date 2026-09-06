"""The two tools the conversation-search capability exposes, and how they read.

The methods are the tools and their docstrings are the whole of what the model
reads before calling them. What comes back is Markdown, because that is what the
model reasons over and what a person reads when the answer is quoted back at them:
a transcript split into `USER:` and `AI:` with the speaker named, not a JSON dump
of rows.

Neither tool takes a person or an organization. Both are resolved server-side from
the run's audience (`app.agents.audience`), so the corpus is one person's - the
person the run is answering - and there is no argument the model can widen.
"""

from __future__ import annotations

from uuid import UUID

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.audience import RunAudience
from app.agents.capabilities._failures import steer
from app.agents.deps import AgentDeps
from app.services import conversation_search as search

# Refusals the model reads as results, not retries: neither is a mistake it can
# correct by calling again with different arguments.
_IN_A_ROOM = (
    "Searching past conversations is off in a group chat. The conversations reachable "
    "from here are one person's own, and quoting one would read it out to everyone in "
    "this channel. It works in a direct message or in the web chat, where that person "
    "is the only one listening."
)
_NO_CORPUS = (
    "Nobody is identified in this conversation, so there are no past conversations to "
    "search. Answer from what you have here."
)

_MAX_TURN_CHARS = 1500
"""How much of one turn is written out before it is cut.

A single pasted document would otherwise fill the whole window on its own and the
rest of the thread would never be reached."""

_MAX_TRANSCRIPT_CHARS = 16000
"""The budget one `read_conversation` answer spends.

A ceiling in characters as well as in turns, because sixty turns of a long thread
is not a bounded amount of text. Whichever runs out first ends the window, and the
answer says where it stopped so the next call resumes there rather than guessing."""


def _one_line(text: str) -> str:
    """Whatever was said, on one line.

    A snippet comes out of `ts_headline` with the message's own newlines in it,
    and a title is generated from a first turn that may have had them too. Left
    alone, the second line of either escapes the `>` it was quoted under and the
    result reads as the tool's own prose rather than as something somebody said.
    """
    return " ".join(text.split())


def _speaker_label(role: str, name: str | None) -> str:
    """`USER`, `AI`, or the role itself - with who it was, when the row knows.

    The name matters in a channel and only there: a room has several people in it,
    and a transcript that called all of them `USER` would be unreadable to a model
    trying to work out who agreed to what.
    """
    label = {"user": "USER", "assistant": "AI"}.get(role, role.upper())
    return f"{label} ({name})" if name else label


class ConversationSearchToolset(FunctionToolset[AgentDeps]):
    """Find and open the past conversations of the person this run answers.

    Concrete in `AgentDeps` (not the capability's `AgentDepsT`) because both tools
    read the run's audience and organization off `ctx.deps`, which a generic dep
    type could not name - the shape `knowledge` and `memory_files` take.
    """

    def __init__(self, *, max_results: int) -> None:
        super().__init__()
        self._max_results = max_results
        self.add_function(self.search_conversations, name="search_conversations")
        self.add_function(self.read_conversation, name="read_conversation")

    def _corpus(self, ctx: RunContext[AgentDeps]) -> tuple[UUID, UUID] | str:
        """(organization_id, user_id), or the refusal to answer with.

        One resolver for both tools, so a search that finds a thread and a read
        that opens it agree by construction.

        **Private audiences only**, and that is the security decision this
        capability turns on. The corpus is one person's - their own threads, what
        was shared with them, the rooms they are still in - so it may only be read
        aloud where that person is the only listener. In a channel the same call
        would quote a private conversation to everyone in it. It is the line
        `may_inject_memory` draws for the same reason, one layer further out: there
        the risk is a colleague writing another colleague's instructions, here it is
        one person's threads becoming another's reading.
        """
        deps = ctx.deps
        audience = deps.audience or RunAudience()
        if deps.organization_id is None:
            return _NO_CORPUS
        if not audience.private:
            return _IN_A_ROOM
        if audience.user_id is None:
            return _NO_CORPUS
        return deps.organization_id, audience.user_id

    async def search_conversations(
        self, ctx: RunContext[AgentDeps], query: str, limit: int | None = None
    ) -> str:
        """Search this person's past conversations for what was actually said in them.

        Reach for it whenever an answer depends on something from before this
        conversation - a decision taken, a number quoted, a name you were given -
        rather than saying you have no record of it. It covers their own
        conversations, ones shared with them, and the group chats they are in; other
        people's are not searchable and never appear.

        Words are matched whole and case is ignored, but word *forms* are not folded
        together: `meeting` does not find `meetings`, and no language is stemmed. If a
        search comes back empty, try another form of the word or a different word
        before concluding nothing was said. Quoted `"exact phrases"`, `or`, and a
        leading `-` to exclude a word all work.

        This finds conversations, not documents. Use the knowledge tools for the
        organization's files, and your own memory tools for what you wrote down
        yourself.

        Args:
            query: The words to look for, as they would have been written in the
                conversation. Two or three specific ones beat a sentence.
            limit: How many conversations to return. Omit for the agent's default;
                anything higher is capped at it.

        Returns:
            One block per conversation, strongest match first - its title, when it
            was last active, how many turns matched, the best matching passage with
            the terms in bold, and the id to open it with. A line saying nothing
            matched when nothing did, and a refusal in a group chat, where searching
            is off.
        """
        corpus = self._corpus(ctx)
        if isinstance(corpus, str):
            return corpus
        organization_id, user_id = corpus
        if not query.strip():
            return steer(ctx, "Send the words to search for; `query` was empty.")
        wanted = self._max_results if limit is None else max(1, min(limit, self._max_results))
        found = await search.search(
            query=query,
            organization_id=organization_id,
            user_id=user_id,
            limit=wanted,
        )
        if not found:
            return (
                f"No conversation you can read mentions {query!r}. Try other words, or "
                "another form of them - word forms are not folded together."
            )
        blocks = [
            "\n".join(
                [
                    f"**{_one_line(hit.title) if hit.title else 'Untitled conversation'}** — "
                    f"last active {hit.updated_at:%Y-%m-%d}, "
                    f"{hit.hits} matching turn{'s' if hit.hits != 1 else ''}",
                    f"id: `{hit.conversation_id}`",
                    f"> {_speaker_label(hit.speaker_role, hit.speaker_name)}: "
                    f"{_one_line(hit.snippet)}",
                ]
            )
            for hit in found
        ]
        return (
            f"{len(found)} conversation{'s' if len(found) != 1 else ''} matched "
            f"{query!r}:\n\n"
            + "\n\n".join(blocks)
            + "\n\nOpen one with `read_conversation`, passing the id exactly as shown."
        )

    async def read_conversation(
        self, ctx: RunContext[AgentDeps], conversation_id: str, skip: int = 0
    ) -> str:
        """Read a past conversation in full, turn by turn, once you have found it.

        Use it after `search_conversations` when a snippet is not enough - the
        passage around a match, or how something was decided. The id comes from
        those results; you cannot open a conversation you have not found, and one
        belonging to somebody else is not readable however the id was obtained.

        Args:
            conversation_id: The id from a `search_conversations` result, copied
                exactly.
            skip: How many turns to skip. Omit to start at the beginning; pass the
                number the previous answer ends with to read on.

        Returns:
            The conversation as Markdown, `USER:` and `AI:` in the order they were
            written, with the speaker named where a room has several people in it.
            Long threads come a window at a time, and the last line says how far it
            got and what to pass as `skip` for the next one. A single very long turn
            is cut and marked.
        """
        corpus = self._corpus(ctx)
        if isinstance(corpus, str):
            return corpus
        organization_id, user_id = corpus
        try:
            wanted = UUID(conversation_id)
        except ValueError:
            return steer(
                ctx,
                f"{conversation_id!r} is not a conversation id. Use one from a "
                "`search_conversations` result, copied exactly.",
            )
        transcript = await search.read(
            conversation_id=wanted,
            organization_id=organization_id,
            user_id=user_id,
            skip=max(0, skip),
        )
        if transcript is None:
            return steer(
                ctx,
                "No conversation you can read has that id. Find one with "
                "`search_conversations` and use the id it gives.",
            )
        return _render(transcript)


def _render(transcript: search.Transcript) -> str:
    """One window of a transcript as Markdown, stopping when the budget runs out.

    The trailing line is load-bearing rather than decorative: without it a model
    handed the first sixty turns of a two-hundred-turn thread reasons about the
    slice as though it were the whole conversation.
    """
    heading = f"# {transcript.title or 'Untitled conversation'}"
    if not transcript.turns:
        return (
            f"{heading}\n\nNothing to read from turn {transcript.skip + 1}: this "
            f"conversation has {transcript.total} turn"
            f"{'s' if transcript.total != 1 else ''}."
        )
    lines = [heading]
    spent = 0
    written = 0
    for turn in transcript.turns:
        body = turn.content.strip()
        if len(body) > _MAX_TURN_CHARS:
            body = f"{body[:_MAX_TURN_CHARS]}… _(turn cut short)_"
        if spent + len(body) > _MAX_TRANSCRIPT_CHARS and written:
            break
        lines.append(
            f"\n**{_speaker_label(turn.role, turn.speaker)}** · {turn.at:%Y-%m-%d %H:%M} UTC\n"
            f"\n{body or '_(no text)_'}"
        )
        spent += len(body)
        written += 1
    first = transcript.skip + 1
    last = transcript.skip + written
    footer = f"\n\n---\nTurns {first} to {last} of {transcript.total}."
    if last < transcript.total:
        footer += f" Call `read_conversation` again with `skip={last}` to read on, if you need to."
    return "\n".join(lines) + footer
