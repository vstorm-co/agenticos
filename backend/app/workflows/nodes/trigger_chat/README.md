# trigger.chat

A workflow the chat can answer with. A member picks it in the chat's list of who
answers and sends a message; the run starts here and its `core.output` text is
written back into that conversation as the answer.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `ChatTriggerOutput` | `prompt`, `conversation_id`, `user_id` |

Only a workflow whose live version starts from this trigger is offered in the
chat. It has no configuration: which conversation the answer goes to is the
member's own, frozen on the run, never a field of the graph.
