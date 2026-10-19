---
title: "Extract invoice data into a spreadsheet"
description: "Attach three synthetic PDF invoices, have an agent read them in a sandbox and write a CSV with fixed columns, and check the one invoice with a missing field is flagged rather than filled in."
---

# Extract invoice data into a spreadsheet

Build an agent that reads a batch of invoices and writes one CSV with the
same columns for every row. The fixture is three small synthetic invoices,
one of them missing its date, so the check that matters is whether the
agent reports the gap instead of inventing a plausible-looking one. This is
a procedure to run, with one recorded run as a reference.

## What you need

- A [running installation](../install.md) with a model profile and a
  registered [sandbox connection](../sandbox.md) offering the `workbench`
  runtime, which carries `liteparse` (`lit`) and `pdftotext` for reading
  PDFs and a Python environment for writing the CSV.
- No knowledge, no charts.

## Prepare the input

Three short invoices, generated as PDFs so the fixture matches what a real
upload looks like. Save this script as `make_invoices.py` in a scratch
directory:

```python
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

def draw_invoice(path, number, date, vendor, lines, tax_rate, include_date=True):
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 30 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, "INVOICE")
    y -= 10 * mm
    c.setFont("Helvetica", 11)
    c.drawString(20 * mm, y, f"Invoice number: {number}")
    y -= 6 * mm
    if include_date:
        c.drawString(20 * mm, y, f"Date: {date}")
        y -= 6 * mm
    c.drawString(20 * mm, y, f"Vendor: {vendor}")
    y -= 6 * mm
    c.drawString(20 * mm, y, "Bill to: Meridian Analytics BV")
    y -= 12 * mm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Description")
    c.drawString(130 * mm, y, "Qty")
    c.drawString(150 * mm, y, "Amount")
    y -= 6 * mm
    c.setFont("Helvetica", 11)
    subtotal = 0.0
    for desc, qty, amount in lines:
        c.drawString(20 * mm, y, desc)
        c.drawString(130 * mm, y, str(qty))
        c.drawString(150 * mm, y, f"{amount:.2f}")
        subtotal += amount
        y -= 6 * mm
    y -= 4 * mm

    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)
    c.drawString(120 * mm, y, "Subtotal:")
    c.drawString(150 * mm, y, f"{subtotal:.2f} EUR")
    y -= 6 * mm
    c.drawString(120 * mm, y, f"Tax ({int(tax_rate*100)}%):")
    c.drawString(150 * mm, y, f"{tax:.2f} EUR")
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(120 * mm, y, "Total:")
    c.drawString(150 * mm, y, f"{total:.2f} EUR")
    c.showPage()
    c.save()
    return subtotal, tax, total

s1 = draw_invoice("INV-1001.pdf", "INV-1001", "2027-01-15", "Nordic Office Supplies",
                   [("Desk chairs, ergonomic", 3, 420.00), ("Standing desks", 2, 260.00)], 0.21)
print("INV-1001", s1)

s2 = draw_invoice("INV-1002.pdf", "INV-1002", "2027-01-22", "Blue Ridge Logistics",
                   [("Freight, Rotterdam-Warsaw", 1, 780.00), ("Customs handling", 1, 195.00)], 0.21)
print("INV-1002", s2)

s3 = draw_invoice("INV-1003.pdf", "INV-1003", None, "Summit Cleaning Services",
                   [("Monthly office cleaning, January", 1, 227.27)], 0.21, include_date=False)
print("INV-1003", s3)
```

Then run it there. It writes `INV-1001.pdf`, `INV-1002.pdf` and
`INV-1003.pdf` beside itself:

```bash
uv run --with reportlab python make_invoices.py
```

`make_invoices.py` draws each one with `reportlab`: an invoice number, a
vendor, a line-item table, a subtotal, 21% tax and a total — `INV-1001` and
`INV-1002` complete, `INV-1003` with no date line at all, on purpose.

The reference values, to check the extraction against:

| Invoice | Date | Vendor | Subtotal | Tax | Total |
| --- | --- | --- | --- | --- | --- |
| INV-1001 | 2027-01-15 | Nordic Office Supplies | 680.00 | 142.80 | 822.80 |
| INV-1002 | 2027-01-22 | Blue Ridge Logistics | 975.00 | 204.75 | 1179.75 |
| INV-1003 | *(missing)* | Summit Cleaning Services | 227.27 | 47.73 | 275.00 |

Every total is subtotal plus 21% tax, so a wrong total is checkable by hand.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Sandbox**. Choose **Container**, select
   your sandbox connection and the `workbench` runtime.
3. Set a budget and a step limit — reading three short PDFs and writing one
   CSV is a handful of tool calls.
4. Set the instructions below, then **Publish**.

```text
You extract structured data from attached invoices.
Read each invoice from the workspace before extracting anything - use lit
or pdftotext to get its text; do not guess from the filename.
Write invoices.csv in the workspace with exactly these columns: invoice_number,
date, vendor, subtotal, tax, total, currency.
If a field is not present on an invoice, leave that cell empty and name the
invoice and the missing field in your reply. Never invent a value that is
not on the document.
Check that subtotal plus tax equals total for each invoice, and say so if one
does not.
```

## Run it

Attach `INV-1001.pdf`, `INV-1002.pdf` and `INV-1003.pdf` to a new
conversation and send:

```text
Extract the invoice data from these three files into invoices.csv, with one row per invoice.
```

Reading a PDF's text on the `workbench` runtime runs `lit` or `pdftotext`
through `execute`, which asks for approval the same way a shell command does
in [Turn a CSV into a chart you can check](csv-chart.md#run-it). Read the
command, then **Approve**; writing the CSV itself needs no approval. The
agent may park on `execute` more than once in the same turn — a first
attempt that writes `lit`'s output to a file outside the workspace, then a
second that prints straight to the command's own output, is one shape this
can take. See the recorded run below.

## Check the result

| Check | Reference |
| --- | --- |
| `invoices.csv` rows | Three, one per invoice, same seven columns in the same order |
| INV-1001 and INV-1002 | Every field matches the reference table exactly |
| INV-1003's date cell | Empty, not a guessed or invented date |
| The reply | Names `INV-1003` and "date" as missing, rather than only leaving the cell blank |
| Totals | Subtotal plus tax equals total on every row; the agent says so if it checked and one doesn't |
| A fourth file that is not an invoice at all | The agent says it could not extract invoice fields from it, rather than inventing a row |

Open `invoices.csv` from the workspace and check it directly — a reply that
lists the right numbers in prose while the file holds something else is a
gap only the file itself shows.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter, `workbench` runtime. The
    agent's first `execute` call ran `lit parse <file> -o /tmp/inv*.md` for
    all three PDFs, then tried `read_file` on `/tmp/inv1001.md` and the
    other two — all three failed, because `/tmp` is outside the workspace
    `read_file` can reach, even though `execute` itself can write there. The
    agent recovered on its own: a second `execute` call re-ran `lit parse`
    for all three files with no `-o`, printing straight to the command's
    output, which it then read directly from the tool result. Both `execute`
    calls needed separate approvals in the same turn.

    `invoices.csv` came out with all three rows and the reference columns,
    every INV-1001 and INV-1002 field matching the source PDFs exactly, and
    INV-1003's `date` cell empty. The reply named "`INV-1003` — `date`" as
    the missing field. Before finishing, the agent ran its own arithmetic
    check with a one-off `execute` — `python3 -c "..."` reading the CSV back
    and comparing subtotal plus tax to total — and reported all three rows
    balanced. Total cost for the run: 0.1302 USD, on 37,246 input and 1,233
    output tokens.

## When it goes wrong

- **The agent guesses a date for INV-1003.** The instructions say to leave
  the cell empty and name the gap; if it still fills one in, add "do not
  infer a date from context" and test again with the same file.
- **The run stops after reading the files.** It is parked on the `execute`
  approval for `lit` or `pdftotext`. Open the chat, or **Approvals** under
  **Activity**. It can park twice in the same turn — see the recorded run
  above.
- **`read_file` fails on a path `lit` just wrote.** `execute` can write
  anywhere in the container, including outside `/workspace`, but `read_file`
  is scoped to the workspace. Have the agent parse straight to the command's
  own output, or write `lit`'s `-o` file inside the workspace, not `/tmp`.
- **A total is off by the tax amount.** Check whether the agent read the
  invoice's own printed total or recomputed one — a fixture this small
  should never need recomputing, and a mismatch usually means a
  misread line item.
- **The CSV has different columns each time.** The instructions name them
  exactly; if the model still varies the order or adds a column, list them
  as a literal header line rather than prose.
- **A PDF with a scanned page reads as empty.** `lit` only OCRs a page with
  no text layer, and a scan costs several seconds a page — see
  [what is in the runtime, and what is deliberately not](../sandbox.md#what-is-in-it-and-what-is-deliberately-not)
  before pointing this agent at scanned invoices rather than generated ones.

## Record the trial

Keep the three source PDFs, the exact prompt, the agent version, the
approved `execute` calls from Activity, and the resulting `invoices.csv` —
not just the chat reply. A person still checks the missing-field report
against the source PDF and decides what to do about the gap; the agent's
job is to surface it, not resolve it.

## Next steps

Once this holds on a batch of three, add a fourth invoice in a different
currency or a different layout, one difficulty at a time, the same way
[Turn a CSV into a chart you can check](csv-chart.md) suggests for its own
fixture.
