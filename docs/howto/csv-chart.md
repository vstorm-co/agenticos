---
title: "Turn a CSV into a chart you can check"
description: "Attach a small synthetic sales file, let the agent calculate and plot it in a sandbox, and reconcile every number with the source rows."
---

# Turn a CSV into a chart you can check

Give an agent a small sales file and ask for monthly totals, a chart and the script that produced them. The fixture is small enough to add up by hand, so every number the agent reports can be checked against the source rows. This is a procedure to run, with one recorded run as a reference. It does not measure accuracy on your own data.

## Prepare the input

Use a [running installation](../install.md) with a model profile. Save this as `sales.csv`:

```csv
month,product,revenue_eur
2026-01,A,120
2026-01,B,80
2026-02,A,150
2026-02,B,100
2026-03,A,90
2026-03,B,110
```

The figures are invented. The reference totals are 200 EUR for January, 250 for February and 200 for March, 650 in total, from six data rows.

## Check the sandbox

The agent reads the file and runs its script in a container. That needs the sandbox service and a registered connection:

- `make dev` and the Docker Compose `sandbox` profile start the service. See [install](../install.md).
- **Sandboxes → Add connection** registers it for the organization. The connection offers the `workbench` runtime, which has `pandas` and `matplotlib`. See [the sandbox](../sandbox.md#which-environments-an-agent-may-ask-for).
- `agenticos cmd doctor` reports whether every registered connection answers with a runtime.

The first session builds the `workbench` image, about 2 GB. Allow a minute or two for the first turn on a fresh host.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Files & shell**. Choose **Container**, not **Files**: the Files workspace has no shell, so the agent cannot run a script. Select the connection and the `workbench` runtime, and keep the conversation scope.
3. Enable **Charts**. It draws numbers the agent already has, so the chart shows what the script calculated.
4. Set a budget and a step limit for the trial. The recorded run used 25 steps and cost about 0.11 USD.
5. Set the instructions below, then **Publish**.

```text
You analyse CSV files the user attaches.
Read the file from the workspace before calculating anything.
Show the totals as a table and state the number of rows you read.
Draw charts with create_chart from numbers you computed.
Save any code and output files in the workspace and give their paths.
Do not fetch data from the internet.
```

## Run it

Open a new chat with the agent, attach `sales.csv` and send:

```text
Sum revenue_eur by month. Return the totals as a table, draw a bar chart of them, and save the calculation script and a PNG of the chart in the workspace.
```

The attachment is written into the workspace under `uploads/`, and the message tells the agent where. [File processing](../file-processing.md) describes the routing.

When the agent wants to run its script, the chat shows **Tool approval required**. Running a shell command is a side effect, so by default a person approves it. Read the command, then **Approve**. The run continues from where it stopped. To skip this for a trusted test agent, change the approval setting of `execute` in the Builder. See [approvals](../governance.md#approvals).

## Check the result

| Check | Reference |
| --- | --- |
| Monthly totals in the reply, the script output and the chart | 200, 250 and 200 EUR, in month order |
| Grand total | 650 EUR |
| Rows read | 6 |
| Chart | Bars start at zero, the axis names the unit |
| Workspace | The script and the PNG exist and open |
| The same message with no file attached | The agent says the file is missing, and invents no data |

Compare each number with the source rows, not with the reply's own summary. Then open the workspace from the chat's files panel. Open the PNG itself and read the script. A path in a reply does not prove that the file exists.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The agent called `read_file` on the upload, `write_file` for `analysis/revenue_by_month.py`, then `execute`, which parked for approval. After approval the script printed the three totals, `Total rows read : 6` and `Grand total (€) : 650`. `create_chart` drew 200, 250 and 200. The workspace held the script and a 1050×600 PNG. Cost: 0.115 USD.

    The final reply gave the totals in prose and listed the saved files, but did not repeat the table or the row count. Those were in the script's output. Without a file, the agent listed an empty workspace and asked for the CSV.

## When it goes wrong

- **The agent says it has no shell.** The capability uses **Files** instead of **Container**.
- **The first turn waits a long time.** The `workbench` image is building. Later sessions reuse it.
- **The run stops after the agent writes its script.** It is waiting for approval of `execute`. Open the chat, or the **Approvals** tab in **Activity**.
- **A connection error names the sandbox.** Run `agenticos cmd doctor`, then check the connection under **Sandboxes**.
- **A total is wrong.** Read the script before changing the prompt. A calculation error and a missing runtime are different problems, and the tool results in Activity show which one happened.

## Record the trial

Keep the exact CSV, the prompt, the agent version, the model profile, the run in Activity, the script and the PNG. Keep failed runs too. If you publish the result, say the data is synthetic and show enough of the table to check the chart.

A person approves the command, compares the totals with the source and opens the files. The agent does not replace that check. It gives you everything you need to do it quickly.

Once this works, add one difficulty at a time: a missing value, a repeated month or a second currency. Each shows how the agent handles data that does not add up cleanly. To repeat the report on a schedule, continue with [schedule a weekly report](scheduled-report.md).
