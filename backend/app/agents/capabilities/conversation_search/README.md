# `conversation_search`

Two tools. `search_conversations` matches words against what was said in past
conversations; `read_conversation` opens one of them, turn by turn, as Markdown
split into `USER:` and `AI:` with the speaker named.

It exists because an agent with memory can only recall what some earlier turn
thought worth writing down. Everything else was said, stored, and unreachable —
so "what did we decide about the Q3 pricing" answered "I have no record of that"
in a product holding the whole exchange (#789).

## Whose conversations, and where

The corpus is **one person's**: the person the run is answering. Three ways in,
the same three `ConversationService._may_read` allows, resolved in
`app/services/conversation_search.py` and passed down as a single SQL predicate:

- conversations they own;
- conversations explicitly shared with them;
- channel threads they took part in **and are still a member of** — confirmed
  against the platform, cached for a minute, failing closed (#641).

The fourth way in that service allows, a trigger's run-log, is deliberately
absent. It is gated on `runs:view` plus the trigger's agent, and an agent
searching on somebody's behalf holds no permission of theirs to check with.

**And only where that person is the only listener.** In a group chat both tools
refuse, in one sentence saying why: the corpus is personal, so answering from it
in a channel would read one person's private conversations out to everybody in
the room. That is the line `may_inject_memory` draws for memory, one layer
further out — there the risk is a colleague authoring another colleague's
instructions, here it is one person's threads becoming another's reading.

A room corpus was considered and is not here. A thread only stays reachable from
its room while `channel_sessions.conversation_id` points at it, and `/new`
re-points that — so "the room's conversations" is the one thread the run is
already in, which the model can already see.

## Keyword, and `simple`

PostgreSQL full-text search: a generated `tsvector` on `messages.content` with a
GIN index (`0074_message_search_vector`), `websearch_to_tsquery` for the query,
`ts_rank_cd` for the order, `ts_headline` for the passage. Not `ILIKE`, which
matches inside words and cannot rank; not pgvector, which is what `knowledge`
already is and answers a different question — "find the passage that means this"
rather than "find where we said this".

The configuration is `simple`, so words are matched whole and case-folded but
**not stemmed**: `meeting` does not find `meetings`. That is a deliberate trade.
The configuration is fixed at the column, `english` would stem one language and
mangle every other, and PostgreSQL ships no Polish dictionary at all — so the
alternative is a search that is quietly worse for half the people using it. The
tool description states the limitation, so a model that finds nothing tries
another form of the word instead of concluding nothing was said.

## What it deliberately does not do

- **No listing.** There is no "show me my conversations" tool: that is the
  sidebar, and a model does not need a paged index of somebody's whole history to
  answer a question about one thread.
- **No writing.** Both tools read. Renaming, archiving and deleting a
  conversation are a person's, through the console.
- **No tool calls in the transcript.** `read_conversation` returns what was said,
  not what was run. The tool calls of a past run are operational detail and would
  be most of the tokens.
- **No cross-person search, at any configuration.** An operator who wants agents
  out of conversations altogether withholds the `conversations:read` scope; there
  is no setting that widens the corpus, because there is no version of "search
  everybody's conversations" that is safe to hand a model.
