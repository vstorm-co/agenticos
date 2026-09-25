---
title: "Schedule a weekly report"
description: "Give an agent a self-contained reporting task, run it on demand, publish the result as an artifact and put it on a weekly schedule."
---

# Schedule a weekly report

Build an agent that writes a short report from the data in its task and publishes it as an [artifact](../artifacts.md) under a stable link. Then put it on a weekly schedule. The fixture includes a row that cannot be used, so you can check that the agent reports it instead of hiding it. This is a procedure to run, with one recorded run as a reference.

The page separates two questions. Does the report come out right? Test that with **Run now**. Does the schedule deliver it? Only a scheduled fire answers that.

## Build the agent

Use a [running installation](../install.md) with a model profile. No sandbox and no embedding model are needed.

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Charts** and **Artifacts**.
3. Set a budget and a step limit for the trial. The recorded runs used 15 steps and cost about 0.05 USD each.
4. Set the instructions below, then **Publish**.

```text
You write short reports from data given in the task.
Use only the rows in the task. Report totals per category and name any row you could not use.
Label the report as synthetic when the task says the data is synthetic.
Publish the finished report with publish_artifact under the name weekly-report.
```

The artifact's name is its identity. Every run of this agent that publishes `weekly-report` adds a version to the same artifact, so the link you share stays the same.

## Create the schedule

Open **Routines → New schedule**, or the agent's **Availability** tab, and choose the agent. Put the data in the message, so a later run does not depend on a file somebody uploaded to an earlier chat:

```text
Create a report for the synthetic period Demo Week.
Use only these CSV rows:
category,amount
Supplies,20
Supplies,30
Travel,15
Travel,abc
Report totals by category in a fictional demo currency and draw a bar chart.
Label the report synthetic and name any row you could not use.
```

For the cadence, choose **At a set time**, then **Days of the week**, tick **Mon** and set **Time (UTC)** to 09:00. The equivalent cron expression is `0 9 * * 1`. The scheduler works in UTC, so convert from your local time. Save, then check the next fire time the schedule shows.

The schedule runs as the member who created it, with that member's access, and its runs are billed to the agent's budget like any other. [Concepts](../concepts.md#trigger) explains why.

## Run it now

Press **Run now** on the schedule. It fires one extra time and leaves the weekly cadence unchanged. The request returns as soon as the worker accepts the fire. The run then appears in the schedule's own conversation, under **Routines** in the chat sidebar.

| Check | Reference |
| --- | --- |
| Totals | Supplies 50, Travel 15 |
| The row `Travel,abc` | Named as unusable, and not counted |
| Label | The report says the data is synthetic |
| Artifact | **Artifacts** lists `weekly-report`, private to you |
| The run in Activity | Surface `schedule`, status completed |
| Run now a second time | A new version of the same artifact, under the same link |

Open the artifact page and read the report there, not only the chat reply. The page is what people will open. It stays private until you share it or create a public link.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The schedule reported its next fire as Monday 28 September, 09:00 UTC. Run now was accepted with `202`, and the run completed on the `schedule` surface about 30 seconds later, for 0.044 USD.

    The agent called `publish_artifact` with the name `weekly-report` and got version 1, private. It then called `create_chart`. The artifact showed Supplies 50 and Travel 15, a synthetic-data label and "Rows excluded (could not be used): Travel, abc". A second Run now added version 2 to the same artifact and link.

    The chart appeared in the run's conversation, not in the artifact. The artifact page has no network access, and the agent wrote the report without an embedded chart.

## What the schedule does not decide for you

- **Where the data comes from.** This fixture is fixed in the message. A real report needs a source the agent can reach on every run, such as a [knowledge collection](set-up-knowledge-base.md), an [MCP connection](../mcp.md) or a sandbox workspace. A schedule cannot guess which newly uploaded file replaces last week's.
- **The reporting period.** Name it in the message or have the agent read the date. A file called "weekly" does not tell the model which dates to include.
- **Who reads it.** A new artifact is private to the person the run was for. Share it, or create a public link, on the artifact page. [Artifacts](../artifacts.md) covers visibility and grants.
- **Approvals.** Neither tool used here needs one. If you add a tool that does, a scheduled run parks until somebody decides, so name who watches the [approvals queue](../governance.md#approvals).

## Watch a real fire

Run now proves the task, not the schedule. After the first Monday at 09:00 UTC, check that a new run appeared in Activity on its own, that the artifact gained a version and that the people who should read it can open it. The **Routines** dashboard card shows each routine's last outcome, so a schedule that starts failing is visible.

A schedule whose creator can no longer run the agent disables itself and records why. See [concepts](../concepts.md#it-runs-as-a-person).

## When it goes wrong

- **Nothing happens on Run now.** The schedule is paused, or the background worker is not running. The worker executes every scheduled and Run now fire.
- **The report has no artifact.** Check that **Artifacts** is enabled and that the instructions name `weekly-report`. The run's tool calls in Activity show whether `publish_artifact` was called and what it returned.
- **Each run makes a new artifact.** The name changed between runs. Keep it fixed in the instructions.
- **A total is wrong or the bad row disappeared.** Tighten the instructions before you schedule anything. A schedule repeats a mistake every week.

## Record the trial

Keep the message, the agent version, the model profile, the cron expression, each run in Activity and each artifact version. Record which fires were Run now and which were scheduled. A person checks the totals, decides who may read the artifact and watches the first real fire.
