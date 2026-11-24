> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Intake and extraction

## Inputs and source scope

Use structured ledger exports, original electronic invoices, authorized AP mailbox messages and attachments, then scans/photos as available. A vendor statement is a reconciliation aid rather than invoice detail. Read the message body as well as attachments because an invoice can be embedded in either. Record unreadable/inaccessible files explicitly. An AP label or forwarding-address setup can be a reviewer recommendation; this skill creates neither.

For card and expense feeds, determine whether the charge is already paid and whether a reimbursement appears in more than one source. Do not create a new payable from a settled charge. Source brand names do not establish available fields or receipt access.

## Extraction fields

| Field group | Evidence to capture |
|---|---|
| Identity | Client/entity, source file/message, page/row, vendor name and verified ledger ID if known. |
| Invoice | Invoice number, issue date, service/supply period, currency and PO/reference. |
| Terms | Due date, payment terms, discount date/amount and original wording. |
| Values | Line description, quantity, unit price, discount, subtotal, freight, tax and total. |
| Review | Extraction confidence, unreadable characters, duplicate candidates, missing documents and proposed coding. |

Keep the raw value and interpretation when OCR is ambiguous. Do not claim OCR ran if the tool only returned a filename. An unreadable amount stays unknown until a source or reviewer resolves it. Foot line totals and subtotal + tax + freight − supported discounts to the invoice total using the document's stated convention. Preserve a discrepancy instead of altering a line to force agreement.

## Dedupe and vendor matching

Match within the same entity and currency using verified vendor identity and invoice number. Same vendor/number is a strong candidate, but credit notes, reused numbering, separate branches and corrections can require review. If one copy lacks a number, compare amount, date, line detail and PO. The source used five-day and ninety-day search windows as examples; choose windows appropriate to the evidence and disclose incomplete history.

Compare against existing unpaid bills, historical payments, card expenses and statement lines. Retain every source reference on the surviving proposal and list held duplicates. Never create a vendor from an OCR variation or branch suffix; propose an existing match and ask where uncertain. A new vendor determination remains a reviewer question.

## Example

An emailed invoice and statement line both refer to invoice 40218 for USD 1,847. Keep one proposed obligation with both references. A photo showing only “1,84…” is not a second supported total: flag the unreadable amount and request the original invoice.
