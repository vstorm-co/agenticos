# Your first agent

This walks the whole path once: a provider key, a model, an agent that answers, a
published version, and a run with a cost against it.

Fifteen minutes, and about a cent of tokens.

You need a running stack first — see [Install](install.md).

!!! tip "The product will walk you through this too"

    The first time anyone signs in, a walkthrough opens on the dashboard, and
    finishing it offers to build the first agent *with* you, operating the real
    dialogs.

    The manual path is still worth reading once, which is what this page is. The
    guided one is described [at the end](#the-guided-walkthrough).

## 1. Store a provider key

**Settings → Vault → Add credential.**

Pick a provider, paste the key, give it a label. The value is sealed immediately,
and there is no endpoint that returns it — what comes back is a label and the last
four characters.

!!! info "Why a vault and not a config file"

    A key in the environment belongs to the deployment. A key in the vault
    belongs to an **organization**, which is what lets one deployment serve
    several tenants without either being able to spend the other's budget.

    The ciphertext is bound to the organization that stored it, and cannot be
    decrypted for another.

## 2. Add a model

**Agents → any agent → Build → Model.**

Choose a provider, then a model, then which stored key pays for it.

The model list comes from the provider where it publishes one, and from a bundled
shortlist where it does not. It is a suggestion, never a constraint — a provider
ships a model the morning after any catalog was warmed, so anything you type is
accepted.

What you just created is a **model profile**: a named model backed by a named key.

Naming it is the point. It lets you rotate the key, or repoint every agent at a
new model, without touching a single agent.

## 3. Build the agent

**Agents → New agent.**

!!! tip "Or start from a template"

    **Agents → Agent templates** ships twenty-eight ready-made agents grouped by
    industry, each with its instructions written, its capabilities switched on
    and the skills it needs installed alongside it.

    One arrives as a **draft** rather than published, and deliberately: a
    template cannot choose your model, and it has never seen your knowledge
    collection. The rest of this page is what you do next either way.

The name becomes the handle it is addressed by from Slack and the API, and it is
frozen at creation — `Support Copilot` becomes `@support-copilot`.

The **Build** tab is instructions and a model, and the instructions are the whole
of the agent's behaviour:

```markdown
You are Support Copilot.

Answer from the product wiki and cite the document you used.
If the wiki does not cover it, say so rather than guessing.
Never quote a price - route those to sales.
```

Write them in Markdown. The model reads the structure, and headings and lists are
what make a long prompt followable.

!!! note "There is no Save button"

    The draft saves itself as you type. A Builder with a Save button is a Builder
    where the tab closed on twenty minutes of instructions.

## 4. Give it capabilities

**Toolbox.**

Each capability shows exactly what it contributes — every tool, its description,
and the arguments the model has to fill in — *before* you switch it on. Reading a
capability is not granting it.

Two things are worth knowing here:

- **A tool's name and description are prompt.** `search_refund_policy` gets
  reached for on questions `search_documents` is passed over for. Both are
  editable per agent.
- **Anything side-effecting asks for approval by default.** The run parks and
  waits for a person. Set it per capability, or per tool.

## 5. Give it something to read

**Knowledge → Collections** for documents. **Skills** for written know-how.

The difference matters:

| | |
|---|---|
| A **collection** is *searched* | The model chooses what to look for, and can never widen where it looks |
| A **skill** is *read* | The agent loads it only when it decides the skill is relevant, so twenty skills cost almost nothing in context |

Each collection says how many documents it holds, because attaching an empty one
produces an agent that searches, finds nothing and says so — which reads as a
broken agent rather than an empty collection.

## 6. Set a limit, and say who is told

**Limits.** A monthly cap in dollars, a step limit, and who hears about it.

The step limit is the one people forget. It catches the other kind of runaway: a
tool loop that is cheap per call and never finishes. A budget only bills for that
one; a step limit stops it.

Under **Alerts**, decide who is told when this agent stops on its cap or parks on
an approval. By default the admins and the agent's owner hear about the budget,
and whoever started the run plus the admins hear about approvals — so a run a
schedule started does not park unwatched.

[Governance](governance.md) has how budgets, approvals and alerts fit together.

## 7. Publish

**Publish** validates the draft first, so this is also where you find out that the
spec references a collection somebody deleted.

!!! success "A spec that references something missing is refused here, never at run time"

    Which is the whole reason validation happens at publish: somebody is looking
    at a form and can fix it, rather than finding out three weeks later in a run a
    schedule started.

Publishing freezes a **version**. Runs record which version executed, so what an
agent did last Tuesday stays answerable after a dozen edits.

## 8. Run it

**Test**, in the header, opens a chat against the published agent. Ask it
something.

Then look at **Activity**: the run, the version it executed, the model it
resolved, the tokens, and what it cost. If a tool needed approval, it is in the
queue there.

## 9. Put it somewhere

**Availability** is where an agent stops being a thing in a Builder:

| | |
|---|---|
| **Exposures** | Who may run it, and how — API keys, public links |
| **Channel bots** | Slack and Telegram. `@support-copilot` in a channel runs as the *sender*, never as the bot |
| **Embeds** | A widget for your own pages |
| **Environments** | Named pointers at versions, so staging and production can differ |

## Export it

**Download** gives you the spec as YAML.

It names references — a model profile, a collection, a secret — and never values,
which is what makes it safe to commit to your own repository and review like code.

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

## Recap

Nine steps, and the shape of them is the shape of the platform:

1. Sealed a **key** in the vault, per organization.
2. Named a **model profile**, so the key and the model can change without the
   agent changing.
3. Wrote **instructions**.
4. Switched on **capabilities**, and left the side-effecting ones asking for
   approval.
5. Attached **knowledge** to search and **skills** to read.
6. Set a **budget** and a **step limit**, and said who is told.
7. **Published**, which froze a version and validated the spec.
8. **Ran** it, and saw what it cost.
9. Made it **reachable** from somewhere other than the Builder.

Everything after this is more of steps 4, 5 and 9.

## The guided walkthrough

The product teaches itself, and it is worth knowing how — because the walkthrough
is also how anybody you hand this to will learn it.

**It shows once, and the ? replays it.** Finishing, skipping or closing it is
remembered against the account rather than the browser, so it does not return on
the next device. The **?** in the header of any walked page replays that page's
tips whenever they are wanted.

It is offered only where there is something to replay. A section with no stops —
the deployment-admin pages — has **no ?** at all, rather than one that opens an
empty walk. Leaving the walkthrough says exactly that, so nobody discovers the
**?** by accident or not at all.

**Finishing it offers to build the first agent together.** That is an interactive
flow, not a spotlight: it points at the real controls, you operate the real
dialogs, and it advances the moment the thing is actually created.

While it runs, the page is **frozen** — everything dims but the one control the
step is about, so you cannot wander off mid-flow and strand a guided step on the
wrong page. The freeze steps aside on its own whenever a dialog or a picker opens,
so the control the step points at is always usable.

It is adaptive. It walks the path above, checks what the organization already has,
and only stops where something is missing — teaching a workspace with no model how
to add one, or telling a builder who lacks the permission to add one so, rather
than walking them in silence to a publish that will refuse an agent with no model.

**Knowledge, skills and MCP are where it does the most.** With one already, the
flow just points at where it attaches. With none, it crosses to that section's own
screen first and *asks there* — "no knowledge base yet, create one?" — so the
question lands where the answer happens.

A yes guides the creation on the spot, and not just to the button: the walk
follows you into the dialog itself, framing each field in turn with what to put in
it — a skill's name the model calls it by, the description that decides when it is
read, the switch to Source where the know-how is written — and moves on when the
thing is actually created.

Then it walks you back by *pointing*: at **Agents** in the sidebar, at the edit
pencil on the very agent you just built, at the Knowledge tab where the new base
attaches. The return leg waits for your click rather than navigating for you, so
it teaches the path through the app rather than performing it. A skip returns to
the builder on its own.

MCP forks the same way but stays in the builder. A server connects with an inline
dialog right there in the Toolbox, so a yes points at that button and the flow
picks up the moment the connection lands — no trip to another page, and none back.

**It does not end at Publish.** After Publish lands, the flow carries you into the
chat, has you pick the agent you just built, and closes only once you have sent it
a first message. A first agent nobody has run is a tour that stopped one step short
of the point.

**Every other section has its own.** Declining guides nobody, and the offer
returns at the end of the Agents **?** walk. Every other section's **?** ends the
same way, offering to create that section's resource — a skill, a knowledge base,
an MCP connection, an organization, a routine.

Two of them are shaped differently on purpose:

- **Routines** ends *past* its own create. A schedule that sits waiting for the
  clock teaches nothing, so the walk's last stop is the fresh row's own **Run
  now**, and the first fire lands in the run log while you watch.
- **Chat** offers a guided run through the chat surface itself: starting a
  conversation, switching which agent answers, changing the model or thinking
  effort for a single chat. Chat can only talk to a *published* agent, so with
  none it opens by offering to build one first, handing straight over to the agent
  flow. Past that it creates nothing, so it advances on Next.

!!! tip "Replay the dashboard's ? once"

    Its customize stop explains the whole editor: adding cards from the catalog
    (the same card more than once, if you want it per agent), dragging them
    between sections, resizing, hiding, renaming and colouring the sections
    themselves, named layouts, and the reset.

    Every arrangement is per-person, so experimenting moves nobody else's page.

## Next

<div class="grid cards" markdown>

- :material-lightbulb:{ .lg .middle } **[Concepts](concepts.md)**

    Spec, version, exposure, trigger, run — the five nouns you just used.

- :material-shield-check:{ .lg .middle } **[Governance](governance.md)**

    Budgets, approvals, alerts, audit.

- :material-account-key:{ .lg .middle } **[Permissions](permissions.md)**

    Who may do what, and to which rows.

</div>
