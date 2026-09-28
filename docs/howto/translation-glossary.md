---
title: "Translate documents with your terminology"
description: "Bind a ten-term glossary to an agent and check that every term is applied, do-not-translate terms and numbers survive, and an ambiguity gets flagged rather than silently resolved."
---

# Translate documents with your terminology

Give an agent a short English document and a skill holding your glossary, and
have it translate into another language while keeping product names, feature
names and other do-not-translate terms in English. The fixture includes a
genuinely ambiguous date, so you can check that the agent flags it instead of
guessing silently. This is a procedure to run, with one recorded run as a
reference.

## What you need

- A [running installation](../install.md) with a model profile.
- No sandbox or embedding model — this agent only needs the
  [skills capability](../reference/capabilities.md#skills) and a chat
  attachment.

## Prepare the input

Save this as a skill, in **Skills → New skill**. Name it `fenwick-glossary`
and give it a description such as "Which terms in a Fenwick Ledger document
stay in English, and the preferred Polish translation for the rest." Fenwick
Ledger is a synthetic accounting product invented for this test.

```text
Fenwick Ledger is a synthetic accounting product used only for this test.

## Keep in English, never translate

- Fenwick Ledger (product name)
- Quick Close (feature name)
- workspace
- API key
- sandbox

## Translate using these terms

| English | Polish |
|---|---|
| ledger | księga |
| invoice | faktura |
| reconciliation | uzgadnianie |
| dashboard | pulpit |
| audit trail | ślad audytu |

Numbers, dates and currency amounts are copied exactly as they appear in the
source — do not reformat a date or convert a currency. If a sentence in the
source could be read two ways, translate the more likely reading and add one
line after the translation flagging the ambiguity and both readings.
```

Then save this synthetic document as `release-notes.md`. The date
`03/04/2026` is deliberately ambiguous between day-first and month-first
reading — that is the case this fixture is built to test.

```text
Fenwick Ledger 4.2 release notes

This release adds Quick Close, a one-click way to close the monthly ledger
once every invoice is matched. Quick Close runs the reconciliation for the
current period and shows the results on the dashboard.

Every action Quick Close takes is written to the audit trail, so a
controller can see which invoices were matched automatically and which
needed a manual review.

To use Quick Close in a shared workspace, generate an API key from Settings
and add it to your sandbox environment before running your first close.

The reconciliation step handles invoices up to EUR 50,000 automatically;
anything above that amount is queued for manual approval.

Close the March books by 03/04/2026, before the quarterly audit begins.

Fenwick Ledger is a synthetic product created for this test; no real company
or software is described here.
```

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Skills** and bind the `fenwick-glossary` skill.
3. Set the instructions below, then **Publish**.

```text
You translate documents into Polish.
Follow the bound glossary skill: never translate the terms it lists as
English-only, and use its preferred Polish translation for the rest.
Copy every number, date and currency amount exactly as it appears in the
source.
If a sentence could be read two ways, translate the more likely reading and
add one line after the translation flagging the ambiguity and both readings.
```

## Run it

Open a new chat with the agent, attach `release-notes.md` and send:

```text
Translate the attached release notes into Polish.
```

## Check the result

| Check | Reference |
| --- | --- |
| Five glossary terms translated | ledger→księga, invoice→faktura, reconciliation→uzgadnianie, dashboard→pulpit, audit trail→ślad audytu |
| Five do-not-translate terms preserved | Fenwick Ledger, Quick Close, workspace, API key, sandbox all appear in English |
| Currency amount unchanged | `EUR 50,000` appears exactly, not converted or reformatted |
| Date unchanged | `03/04/2026` appears exactly, not reformatted to a Polish date style |
| Ambiguity flagged | A separate note names both readings of `03/04/2026` |
| Same request with no file attached | The agent asks for the document rather than translating nothing |

Read the Polish text against the glossary term by term; do not trust a summary
that only lists the terms found.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The agent called
    `load_capability` for `fenwick-glossary`, then translated the whole
    document in one reply. All five glossary terms were translated correctly
    and all five do-not-translate terms — including `workspace`, `API key` and
    `sandbox` inside Polish sentences — were left in English. `EUR 50,000` and
    `03/04/2026` were copied unchanged. Cost: 0.017 USD.

    The agent added a flagged note after the translation: read as day-first,
    03/04/2026 is 3 April 2026 (used in the translation); read as
    month-first, it is 4 March 2026. It recommended confirming which was
    meant. With no file attached, it loaded the glossary and then asked for
    the document instead of translating nothing.

## When it goes wrong

- **A do-not-translate term gets translated anyway.** The model may be
  treating it as ordinary vocabulary rather than a proper noun; put the list
  first in the skill body and repeat the instruction in the agent's own
  instructions.
- **A number changes.** Ask the agent to quote the source sentence beside its
  translation; a mismatch is visible immediately.
- **The ambiguity is resolved silently.** Tighten the instructions to require
  a separate flag line rather than leaving the choice to the skill's default
  wording.
- **The agent translates with no file attached.** Tighten the instructions to
  require refusing when no document is present.

## Record the trial

Keep the source document, the glossary body, the translation, the agent
version and the run in Activity. A person who reads the target language still
checks the translation's fluency and confirms which reading of a flagged
ambiguity was actually meant — the glossary and the checks above catch
terminology and preserved values, not whether the sentence reads naturally.

## Next steps

For a production glossary, keep it in one skill per language pair rather than
one skill with every language mixed together, so a translator can review and
edit just their pair. The [DeepL entry](../mcp.md#automation-storage-productivity-media)
in the MCP catalog is an alternative translation engine to connect instead of
using the model directly; this page does not use it.
