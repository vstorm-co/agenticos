> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Matching and exceptions

Where purchase orders exist, compare the invoice to both the PO and receiving record. Confirm entity, vendor, currency, item/unit, quantity, unit price, tax, freight and dates. A document match does not prove delivery or tax eligibility where that evidence is absent.

## Tolerances

Use the engagement's approved price, quantity and rounding tolerances. Source examples are illustrative; do not install a universal amount/percentage rule. Show both values and the absolute/percentage difference. A quantity not received remains an exception even when its amount is small unless an applicable policy explicitly addresses it.

## Exception register

| Exception | Reviewable wording |
|---|---|
| Price above PO | Invoice price, PO price, quantity and proposed disputed difference. |
| Billed more than received | Billed quantity, documented received quantity and unsupported units. |
| Received but unbilled | Receipt date/evidence and possible accrual question, without inventing a bill. |
| Billed but not received | Missing receipt evidence and delivery question. |
| Possible duplicate | Both source identifiers and matching fields; status held for review. |
| Unreadable field | Exact file/page and missing field; no guessed replacement. |
| No PO | Whether the business requires a PO for this transaction, rather than an automatic error. |

## Vendor statements

Reconcile statement entries to source invoices, payments and credit notes. Separate known invoices, missing invoices, payments in transit and disputed items. Do not create a proposed invoice line solely from a statement total lacking underlying detail. Preserve aging even when a line is held.

## Handoff

Prepare factual vendor-question drafts and internal reviewer questions separately. Include the invoice number and exact discrepancy; do not send or queue either. Carry unresolved items to `payment_run.md` so excluded obligations remain visible.
