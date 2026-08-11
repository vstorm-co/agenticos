# Your first agent

This walks the whole path once: a provider key, a model, an agent that answers,
a published version, and a run with a cost against it. Fifteen minutes, and about
a cent of tokens.

You need a running stack - see [Install](install.md).

## The guided way

The steps below are the manual path, and worth reading once. But a new user does
not start here: the first time anyone signs in, a walkthrough opens on the
dashboard and points out each section in turn. It shows **once** - finishing,
skipping or closing it is remembered against the account, not the browser, so it
does not return on the next device - and the **?** in any page header replays that
page's tips whenever they are wanted.

Finishing the walkthrough offers to build the first agent *together*. That is an
interactive flow, not a spotlight: it points at the real controls, the reader
operates the real dialogs, and it advances the moment the thing is actually
created. While it runs the page is **frozen** - everything dims but the one
control the step is about, so the reader cannot wander off mid-flow and strand a
guided step on the wrong page; the freeze steps aside on its own whenever a dialog
or a picker opens, so the control the step points at is always usable. It is
adaptive - it walks the path below, checks what the organization already has, and
only stops where something is missing, teaching a workspace with no model how to
add one - or, for a builder who lacks the permission to add one, saying so rather
than walking them in silence to a publish that will refuse an agent with no model
- and skipping straight past a prerequisite already in place.

Knowledge, skills and MCP servers are where it does the most. With one already,
the flow just points at where it attaches. With none, it *asks* - "no knowledge
base yet, create one?" - and if the answer is yes it runs the whole round trip:
across into the Knowledge section, through creating the base, then back again by
pointing at **Agents** in the sidebar, the edit pencil on the very agent just
built, and the Knowledge tab where the new base attaches. The return leg is taught
by pointing and waiting for the click, not by navigating for the reader, so it
teaches the path through the app rather than performing it. Skills work the same
way. MCP forks the same way but stays in the builder: a server connects with an
inline dialog right there in the Toolbox, so a "yes" points at that button and
the flow picks up the moment the connection lands - no trip to another page, and
none back.

Declining guides nobody; the offer returns at the end of the Agents **?** walk.
Every other section's **?** ends the same way, offering to create that section's
resource - a skill, a knowledge base, an MCP connection, a workspace - and the
Chat **?** offers a guided run through the chat surface itself: starting a
conversation, switching which agent answers, and changing the model or thinking
effort for a single chat. Chat can only talk to a *published* agent, so if there
is none it opens by offering to build one first - a yes hands straight over to the
agent flow. Past that it creates nothing, so it advances on Next rather than on
anything appearing.

## 1. Store a provider key

**Settings → Vault → Add credential.**

Pick a provider, paste the key, give it a label. The value is sealed immediately
and there is no endpoint that returns it: what comes back is a label and the last
four characters.

!!! info "Why a vault and not a config file"

    A key in the environment belongs to the deployment. A key in the vault
    belongs to an organization, which is what lets one deployment serve several
    tenants without either of them being able to spend the other's budget - the
    ciphertext is bound to the organization that stored it and cannot be
    decrypted for another.

## 2. Add a model

**Agents → any agent → Build → Model.**

Choose a provider, then a model from the catalog, then which stored key pays for
it. The model list comes from the provider where it publishes one, and from a
bundled shortlist where it does not - and it is a suggestion, never a
constraint. A provider ships a model the morning after any catalog was warmed, so
anything you type is accepted.

This creates a **model profile**: a named model backed by a named key. Naming it
is what lets you rotate the key, or repoint every agent at a new model, without
touching a single agent.

## 3. Build the agent

**Agents → New agent.** The name becomes the handle it is addressed by from Slack
and the API, and it is frozen at creation - `Support Copilot` becomes
`@support-copilot`.

The **Build** tab is instructions and a model. Instructions are the whole of the
agent's behaviour:

```markdown
You are Support Copilot.

Answer from the product wiki and cite the document you used.
If the wiki does not cover it, say so rather than guessing.
Never quote a price - route those to sales.
```

Markdown, and the model reads the structure: headings and lists are what make a
long prompt followable.

The draft saves itself as you type. There is no Save button because a Builder
with one is a Builder where the tab closed on twenty minutes of instructions.

## 4. Give it capabilities

**Toolbox.** Each capability shows exactly what it contributes - every tool, its
description, and the arguments the model has to fill in - before you switch it
on. Reading a capability is not granting it.

Two things are worth knowing here:

- **A tool's name and description are prompt.** `search_refund_policy` gets
  reached for on questions `search_documents` is passed over for, and both are
  editable per agent.
- **Anything side-effecting asks for approval by default.** The run parks and
  waits for a person. You can set that per capability, or per tool.

## 5. Give it something to read

**Knowledge → Collections** for documents, **Skills** for written know-how.

The difference matters. A collection is *searched* - the model chooses what to
look for and can never widen where it looks. A skill is *read*: the agent loads
it only when it decides the skill is relevant, so twenty skills cost almost
nothing in context.

Each collection says how many documents it holds, because attaching an empty one
produces an agent that searches, finds nothing and says so - which reads as a
broken agent rather than an empty collection.

## 6. Set a limit and say who is told

**Limits.** A monthly cap in dollars, a step limit, and who hears about it.

The step limit is the one people forget: it catches the other kind of runaway, a
tool loop that is cheap per call and never finishes. A budget only bills for that
one; a step limit stops it.

Under **Alerts**, decide who is told when this agent stops on its cap or parks on
an approval. By default the admins and the agent's owner hear about the budget,
and whoever started the run plus the admins hear about approvals - so a run a
schedule started does not park unwatched.

See [Governance](governance.md) for how budgets, approvals and alerts fit
together.

## 7. Publish

**Publish** validates the draft first, so this is also where you find out that
the spec references a collection somebody deleted. A spec that references
something missing is refused *here*, never at run time.

Publishing freezes a version. Runs record which version executed, so what an
agent did last Tuesday stays answerable after a dozen edits.

## 8. Run it

**Test** in the header opens a chat against the published agent. Ask it
something.

Then look at **Activity**: the run, the version it executed, the model it
resolved, the tokens and what it cost. If a tool needed approval, it is in the
queue there.

## 9. Put it somewhere

**Availability** is where an agent stops being a thing in a Builder:

| | |
|---|---|
| **Exposures** | Who may run it, and how - API keys, public links |
| **Channel bots** | Slack and Telegram. `@support-copilot` in a channel runs as the *sender*, never as the bot. |
| **Embeds** | A widget for your own pages |
| **Environments** | Named pointers at versions, so staging and production can differ |

## Export it

**Download** gives you the spec as YAML. It names references - a model profile,
a collection, a secret - and never values, which is what makes it safe to commit
to your own repository and review like code.

```yaml
name: Support Copilot
instructions: |
  You are Support Copilot.
  Answer from the product wiki and cite the document you used.
model_profile_id: 8f1c...
capabilities:
  - id: knowledge
    config: { default_top_k: 8 }
collection_ids: [b2a9...]
budget:
  monthly_usd: 50
```

## Next

- [Concepts](concepts.md) - spec, version, exposure, run.
- [Governance](governance.md) - budgets, approvals, alerts, audit.
- [Permissions](permissions.md) - who may do what, and to which rows.
