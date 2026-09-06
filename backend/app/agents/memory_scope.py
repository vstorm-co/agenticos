"""Which memory store a run may touch, and whether it may be read as instructions.

A memory note records *whose* it is (`owner_key`, in `app.core.memory_keys`). A
run records *who will hear the answer* (`RunAudience`, in `app.agents.audience`).
Keeping the two apart is the whole of the memory access model, because collapsing
them is what let a note taken in a private conversation be read back aloud in a
group channel: "this person's store" and "somewhere only this person is
listening" are not the same fact, and one column cannot hold both (#788).

This module is the join between them, and it lives outside `app.agents.audience`
because the audience is not memory's - conversation search reads the same fact and
has no store at all.

**A run touches exactly one store: the conversation's own.** In a room that is the
room's; alone with somebody, that person's; anonymous, none at all - and then
memory contributes nothing, which is the honest answer rather than a bug.

That is deliberately not "read a union, write the narrowest". There used to be an
organization-wide store every run also read, and with it a precedence order, a
name-clash resolution and a per-store label. It went because it was a second
mechanism for what `context` already does - standing knowledge a person authors
and binds to agents - and one job with two mechanisms is how the two disagree
(#1470). Memory is what the *agent* learned; anything a human writes belongs in
`context`.
"""

from __future__ import annotations

from app.agents.audience import RunAudience
from app.core.memory_keys import person_owner_key

__all__ = ["may_inject_memory", "memory_owner_key"]


def memory_owner_key(audience: RunAudience, *, allow_personal: bool) -> str | None:
    """The one store this run reads and writes, or `None` when it has none.

    Read and write are the same key on purpose. A run that could write somewhere
    it cannot read would be saving into a void; one that could read somewhere it
    cannot write is the union this design removed.

    `allow_personal` off (the operator's compliance lever) drops the person store,
    so an agent configured that way has memory in group chats and none one to one
    - rather than a refusal that suggests an alternative leading to the same
    refusal.
    """
    if audience.room_key is not None:
        return audience.room_key
    if audience.user_id is None or not allow_personal:
        return None
    return person_owner_key(audience.user_id)


def may_inject_memory(audience: RunAudience, *, allow_personal: bool) -> bool:
    """Whether this run's index may be spliced into its own instructions.

    Only where the reader is the sole listener. A tool result is something a model
    weighs; the instructions are what it obeys, so injected content must be
    content its reader alone could have influenced.

    A room fails that even though the run reads it: the speaker is known but is
    not the only listener, so a sentence one colleague left there would arrive as
    another colleague's instructions in the same channel. It stays reachable with
    `read_memory`, which is a result rather than an order (#788).
    """
    return (
        audience.private and memory_owner_key(audience, allow_personal=allow_personal) is not None
    )
