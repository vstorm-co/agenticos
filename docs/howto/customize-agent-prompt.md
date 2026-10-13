# Write an agent's instructions

!!! danger "Instructions are data, not code"

    There is no `prompts.py` to edit, and no `DEFAULT_SYSTEM_PROMPT` constant to
    override. An agent's behaviour is the `instructions` field of its
    [spec](../reference/spec.md) — edited in the Builder, versioned on publish,
    and exported as YAML into a client's own repository. Editing Python to change
    what an agent says is the single most common wrong assumption about this
    codebase.

## Where the text lives

| | Where | Who edits it |
|---|---|---|
| One agent's instructions | `AgentSpec.instructions`, edited in the Builder | Whoever may edit the agent |
| An inline specialist's instructions | `InlineSpecialistSpec.instructions`, in the same spec | Same |
| The starting text a new agent gets | `backend/app/agents/default_instructions.py` | A deploy — it is this deployment's idea of an assistant |
| A procedure many agents share | A [skill](../skills.md), a row in the database | A support lead, on a Tuesday afternoon, with no deploy |

The last row is the one worth reaching for. Twenty procedures in one
`instructions` field means every run pays for all twenty; twenty skills cost
almost nothing, because the model sees the names and loads only what it needs.

## What belongs in instructions

Read `default_instructions.py` before writing your own — it is the worked example,
and it explains its own choices. Two of them decide most of the quality:

- **Write for the refusals.** The paragraphs that earn their place are the ones
  about not inventing facts, saying which source an answer came from, and stopping
  to ask rather than guessing at something destructive. "Be helpful" is
  decoration: the model is already trying to be helpful, and what it needs is
  where the edges are.
- **Put what is specific to *this* agent at the top.** Whoever opens it next will
  rewrite the first paragraph and keep the rest.

```text
You are a customer support agent for Acme.

Answer questions about our products, help people troubleshoot, and escalate
anything involving a refund over £500 — the refund-policy skill has the rule.

Never quote a price you have not read from the knowledge base. If a question
needs an account change, say what you would do and ask them to confirm.
```

!!! warning "Do not list the agent's tools in its instructions"

    An agent gets its capabilities from its spec and the tools carry their own
    descriptions from the library. A prompt that enumerates them is wrong the
    moment somebody toggles one — and the failure is an agent confidently
    refusing to do something it can now do.

!!! tip "Do not restate a capability's own rules either"

    A capability that needs the model to behave a certain way contributes that
    itself. Citation format for retrieval, how to use the sandbox, when to ask a
    person — those arrive with the capability, in every agent that enables it.

## Knowledge, skills and context files

Three ways to give an agent text it did not have, and they are not
interchangeable:

| | For | Retrieved by |
|---|---|---|
| `collection_ids` — [knowledge](../file-processing.md) | Thousands of documents: what we know | Semantic search, cited |
| `skill_ids` — [skills](../skills.md) | Tens of procedures: how we do this | The model picking a name, then loading the body |
| `context_ids` — context files | A handful of files small enough to always be present | Injected into the instructions, no search involved |

All three are checked against the **publisher's** access at publish time, not at
run time. See [Permissions](../permissions.md).

## Iterating on it

- **A draft cannot run.** An agent runs its published version, so trying a new
  prompt means publishing one — which is cheap by design, and why a rollback is a
  promote rather than a restore. Iterate on a `dev`
  [environment](../concepts.md#version) that follows every publish, and leave
  `production` waiting to be promoted onto.
- **Test with real queries, not ideal ones.**
- **Keep it as short as the behaviour needs.** A longer prompt is paid for on
  every turn of every run, and pushes the conversation out of the window sooner.
- **Publish when it is right.** Publishing freezes the version, so "what did this
  agent do last Tuesday" stays answerable after a dozen edits — and a rollback
  publishes a *new* version copied from the old one rather than deleting history.
- **Temperature and the rest are `model_settings`**, per agent and per
  specialist, on top of the model profile. Not an environment variable.
