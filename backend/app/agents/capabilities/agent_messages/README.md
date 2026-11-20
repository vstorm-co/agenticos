# Agent messages

Direct messages between two agents, in a thread the console shows. One thread
per pair of agents, per organization; a message is stored, never delivered as
a run.

## What it is for

Delegation hides multi-agent work: a parent asks a delegate, and only the
parent ever sees the exchange. Messaging is the open version of that - a
researcher tells a summariser what it found, a reviewer asks the author for a
missing file - and anyone who may run either agent can open the thread and
read it.

## Tools

- `agent_send_message` — send as this agent, to another agent by slug or id.
  A reply names the message it answers; up to ten already-uploaded files ride
  along. The message waits in the thread; it does not start the other agent.
- `agent_read_messages` — read one thread, oldest first.
- `agent_list_threads` — the threads this agent is in, most recently active first.
- `agent_react` — one emoji on a message; sending it again takes it back.

## Rules

- Both agents must be published, and the sender needs `agents:run` on both.
  A reader needs `agents:run` on either one.
- A message never starts a run of its recipient, and never wakes it up.
- A reaction as an agent names one of the thread's two agents; reacting
  without one is the reader themself.
- Files are links to uploads the sender already made, not copies. A file is
  readable by anyone who may read the thread.
