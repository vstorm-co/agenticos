---
title: "Build your first document agent"
description: "Give an agent a small handbook, ask a question and check the answer against the source."
---

# Build your first document agent

Build an assistant that answers equipment-policy questions from one document. This synthetic fixture gives you a fact to check and a deliberate information gap. This is a procedure to run, with one recorded run as a reference.

## Prepare the source

Use a [running installation](../install.md) and a configured model. Follow [your first agent](../first-agent.md) for the provider credential and model setup. Costs depend on the selected provider and configuration.

Save this text as `equipment-handbook.md`:

```text
Equipment requests go to the office manager.
Include the item, reason and delivery location.
```

These are invented policy facts. No spending allowance is stated.

## Build and publish

1. In **Knowledge → Collections**, open the create dialog and expand **Embeddings**. Select a compatible embedding provider/model and its vault credential or local endpoint, then create the collection and upload the file. A chat model alone is insufficient. Wait for processing and check the document status.
2. Create an agent in **Agents → New agent** and select your model profile.
3. In **Toolbox**, enable knowledge and bind only the test collection. Set the instructions below.
4. Set a budget and step limit appropriate to the trial, then **Publish** the version you will test.

```text
Answer equipment-policy questions from the bound handbook.
Cite the document you used.
If it does not contain the answer, say what is missing.
Do not invent policies or submit equipment requests.
```

## Check the result

| Question | Reference check |
| --- | --- |
| Who handles an equipment request? | Names the office manager, supported by the source |
| Which details should I include? | Item, reason and delivery location |
| How much can I spend? | Says the allowance is absent from the source |

Ask in a fresh test conversation. Inspect the answer and the retrieved material in [Activity](../governance.md). Keep incorrect or incomplete answers as well as successful ones. If retrieval is empty, check collection binding, permissions and processing before changing the prompt.

Change the owner to the facilities team in the test file. In the [collection document list](../file-processing.md), delete the original test document and wait for deletion to finish before uploading the edited file. Uploading the same filename alone does not replace the old vectors. Wait for processing and repeat in a fresh conversation. Check that obsolete material is not still being retrieved.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter, knowledge search bound to the one collection. "Who handles an equipment request?" called `search_documents` once and answered "equipment requests go to the office manager," with the three details, citing `equipment-handbook.md`. "How much can I spend?" called `search_documents` twice and answered that the handbook "does not contain any information about spending limits or purchase approval thresholds." Cost across the three questions and one retry below: 0.043 USD.

    "Which details should I include?" first returned a clarifying question ("could you clarify what you're referring to?") instead of searching — asked alone in a fresh conversation, the phrase does not carry the equipment-request topic. A second attempt of the same question called `search_documents` and answered correctly. Word it with the subject named if you want the search to run on the first try.

    After deleting the original document, confirming the list was empty, and uploading the edited file, the same first question in a new conversation answered "equipment requests go to the facilities team" with no mention of the office manager. Total cost for the five turns: 0.055 USD.

## Share the next step

Once you have checked the result, put the agent [in Slack](slack-handbook-assistant.md) or choose [another entry point](../channels.md). The hosted page is public by link: use public or synthetic material there. Channel choice does not establish document access rules.

Before a team pilot, assign the [operating owner](../rollout.md). If a step fails, include the version, configuration and redacted reproduction in a [help request](../help.md).
