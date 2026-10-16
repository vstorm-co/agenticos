---
title: "Build an Excel report and a slide deck from data"
description: "Attach a small synthetic CSV and have an agent in a sandbox produce a workbook with formulas and a chart, plus a three-slide deck, then open both and check the numbers."
---

# Build an Excel report and a slide deck from data

Give an agent a sandbox and a small sales CSV, and have it build a workbook
with a formula-driven summary sheet and a chart, then a three-slide deck
covering the same numbers. The fixture is small enough to total by hand, so
you can check every cell against the source rows. This is a procedure to run,
with one recorded run as a reference. If a report is all you need, start with
[turn a CSV into a chart you can check](csv-chart.md) instead — this page adds
a full workbook and a deck on top of that pattern.

## What you need

- A [running installation](../install.md) with a model profile and a
  registered [sandbox connection](../sandbox.md) whose default runtime is
  `workbench` — it carries `openpyxl` and `python-pptx`, so no package
  installation step is needed.
- The synthetic CSV below, small enough to check by hand.

## Prepare the input

Save this as `sales.csv`. Four quarters, four regions, sixteen rows.

```csv
quarter,region,revenue_usd,units
Q1,North,12000,300
Q1,South,9000,250
Q1,East,15000,320
Q1,West,8000,200
Q2,North,13000,310
Q2,South,9500,260
Q2,East,16000,330
Q2,West,8500,210
Q3,North,14000,320
Q3,South,10000,270
Q3,East,17000,340
Q3,West,9000,220
Q4,North,15000,330
Q4,South,10500,280
Q4,East,18000,350
Q4,West,9500,230
```

Reference totals, computed by hand: North 54,000, South 39,000, East 66,000,
West 35,000 by region; Q1 44,000, Q2 47,000, Q3 50,000, Q4 53,000 by quarter;
grand total 194,000.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Sandbox**. Choose **Container**, select
   your sandbox connection and the `workbench` runtime, and keep the
   conversation scope.
3. Set a budget for the trial, then set the instructions below and
   **Publish**.

```text
You build spreadsheets and slide decks in your workspace from data the user
attaches.
Read the attached file before calculating anything.
Use openpyxl to build the workbook and python-pptx to build the deck.
Save every output file in the workspace and give its path.
Do not fetch data from the internet.
```

## Run it

Open a new chat with the agent, attach `sales.csv` and send:

```text
Using the attached CSV, build report.xlsx with a summary sheet totalling
revenue by region and by quarter (use SUM formulas over a raw-data sheet, not
hand-typed numbers) plus a bar chart of revenue by region. Then build a
3-slide summary.pptx: a title slide, a slide with the totals table, and a
slide with the chart or its key numbers. Save both files in the workspace.
```

When the agent runs its script, the chat shows **Tool approval required**.
Read the command, then **Approve**. See [approvals](../governance.md#approvals).

## Check the result

| Check | Reference |
| --- | --- |
| Region totals | North 54,000, South 39,000, East 66,000, West 35,000 |
| Quarter totals | Q1 44,000, Q2 47,000, Q3 50,000, Q4 53,000 |
| Grand total | 194,000 |
| Summary sheet uses formulas | Click a total cell and see `=SUM(...)`, not a typed number |
| Chart | Bars per region, axis labelled with the currency |
| Deck | Three slides: title, totals table, chart or key numbers |
| Numbers match between the workbook and the deck | The deck's totals equal the workbook's, not independently rounded |

Open `report.xlsx` and `summary.pptx` from the chat's files panel and check
them yourself — a path in a reply does not prove the file exists or that its
formulas compute the right number.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The agent read the CSV, wrote
    a 460-line build script and ran it — one `execute` call, approved. It then
    made three more `execute` calls to convert the deck through LibreOffice
    into per-slide PNGs so it could look at its own work, each approved in
    turn.

    `report.xlsx` held a `Raw Data` sheet with all 16 rows and a `Summary`
    sheet whose every regional and quarterly cell was a live `SUMPRODUCT`
    formula against `Raw Data`, with `SUM` row and column totals and a
    clustered bar chart — no hand-typed number anywhere. Evaluating those
    formulas against the raw data gives North 54,000, South 39,000, East
    66,000, West 35,000, and 44,000/47,000/50,000/53,000 by quarter, 194,000
    overall — the reference totals exactly.

    `summary.pptx` held three slides: a title slide with the grand total, a
    full region-by-quarter table matching the workbook cell for cell, and a
    chart-and-KPI slide repeating the four region totals. Cost: 0.37 USD
    across four approval round trips.

## When it goes wrong

- **The agent says it has no shell.** The capability uses **Files** instead
  of **Container** — switch to Container and pick the `workbench` runtime.
- **A total is a typed number, not a formula.** Ask it to rebuild the summary
  sheet with `SUM` or `SUMPRODUCT` formulas referencing the raw-data sheet;
  a hand-typed number does not update if a row changes.
- **The workspace briefly refuses every write.** This happened once during
  verification, when the underlying sandbox host had lost its Docker socket
  permission; every `write_file` failed and the agent fell back to printing
  the script as text instead of running it. `agenticos cmd doctor` and the
  connection's status under **Sandboxes** show whether the service can
  actually start a session.
- **The deck's numbers do not match the workbook.** The agent may have
  hand-typed the deck's totals separately; ask it to compute the deck's
  numbers from the same values the workbook's formulas produce.
- **The first turn is slow.** The `workbench` image is building; later
  sessions reuse it.

## Record the trial

Keep the CSV, the prompt, the agent version, the run in Activity, and both
output files. Open the workbook's formulas, not just its displayed numbers,
before trusting a total.

A person checks that the formulas are real formulas, that the chart's axis
means what it says, and that the deck is something they would actually hand
to someone else. The agent gives you the files; it does not replace opening
them.

## Next steps

For a report that has to run every week rather than once, continue with
[schedule a weekly report](scheduled-report.md), which publishes its output
as a stable, shareable app instead of a workspace file.
