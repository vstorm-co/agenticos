> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Collection-draft failure cases

## Payments outside the connected processor

A PayPal/Stripe check does not establish whether a customer paid by bank transfer, cheque or another processor. State the actual source coverage and date windows. Hold a reminder when current nonpayment is unresolved; do not turn unavailable data into a claim that the customer failed to pay.

## Internal/test records

Inspect actual record purpose and engagement scope. A test-like name or matching email domain is a review flag, not conclusive evidence that a receivable should be excluded. Report exclusions and their basis.

## Duplicate invoices and recipients

The ledger and a processor can represent the same invoice. Prefer verified cross-system identifiers and preserve amount/currency/date evidence. Fuzzy matching by name alone is uncertain. Produce one consolidated draft per verified customer, rather than multiple reminders for duplicate representations.

## Rate limits and partial windows

Follow the current tool's retry rules. The upstream snapshot used narrower PayPal windows to reduce rate-limit errors, but that is not a universal API rule. Record any reduced lookback, missing pages or failed source and the unresolved settlement check. Do not repeatedly retry a blocked operation or claim a full-period check after a partial read.

## Lifecycle status and numbering

An unpaid field may coexist with void/cancelled status. Validate both. A processor's assigned invoice number can differ from the customer-facing ledger reference; inspect explicit metadata/mappings before substituting it. A paid-status mismatch is a reconciliation exception, not permission to alter either system.

## Payment links and mail

Reuse only an existing verified link for the correct entity, invoice, currency and amount. Do not create a link, add an email recipient to a payment-link API or invoke a reminder-send endpoint. A missing send capability is irrelevant to this skill's deliverable: return full copyable drafts and the remaining recipient/evidence questions. Do not fall back from a failed send to another sending route, because this workflow performs no sends.

## Production and tenant identity

Confirm account identifiers and production/sandbox status using actual evidence. Do not assume a particular server label always represents production. If the connected data belongs to a different entity or test environment, exclude it and obtain the intended scoped input before computing client balances.
