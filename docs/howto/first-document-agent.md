---
title: "Build your first document agent"
description: "Give an agent a small handbook, ask a question and check the answer against the source."
---

# Build your first document agent

Build an assistant that answers equipment-policy questions from one document. This synthetic fixture gives you a fact to check and a deliberate information gap. It is a procedure to run, not a report of a measured deployment result.

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

## Share the next step

Once you have checked the result, choose [Slack or another entry point](../channels.md). The hosted page is public by link: use public or synthetic material there. Channel choice does not establish document access rules.

Before a team pilot, assign the [operating owner](../rollout.md). If a step fails, include the version, configuration and redacted reproduction in a [help request](../help.md).
