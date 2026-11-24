> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Additional evidence sources for collection drafts

Use the engagement's confirmed ledger for open balances, authorized processors for settlements and a permitted contact source for recipient evidence. A connector is useful only when its current schema and account cover the required read; this file guarantees no product endpoint.

| Evidence | Required fields and checks |
|---|---|
| AR ledger | Entity, customer/invoice ID, currency, open amount, due date, credits and cut-off; reconcile total to the control account. |
| Processor invoices | External and ledger references, lifecycle/payment status, amount, currency and invoice/customer mapping. |
| Settlements | Transaction ID, date, currency, amount, fees/refunds and supported invoice allocation. |
| Bank/cheque receipts | Value date, receipt/reference and confirmed allocation; do not assume these appear in a processor. |
| Recipient directory | Verified customer relationship and current email; preserve the record source and flag ambiguity. |
| Payment instructions | Existing verified invoice link or approved instructions; no link creation or payee change. |

The upstream examples included MYOB, NetSuite, QuickBooks, Xero, Zoho Books, PayPal, Stripe, Square, Shopify and Airwallex. Those brand names are illustrative source categories. If a particular connection omits emails, balances, histories or lifecycle fields, request the missing evidence rather than claiming a product-wide limitation.

## Reconciliation

Read only relevant authorized sources and deduplicate the same invoice/settlement. Use explicit ledger reference mappings where available; a processor's own number may be different. Customer plus amount plus date is a candidate match requiring review, particularly for common amounts or recurring invoices. Keep original references.

Set a lookback appropriate to posting delays. Report the actual interval covered by each source and the effect of failed/limited reads. A recently paid or possibly paid customer is held from the ready draft batch until allocation is resolved.

## Draft handoff

Return the full draft, verified recipient, source invoice lines, current balance/currency, tone rationale, payment checks and status. A separate authorized operational workflow may send it later after refreshing time-sensitive balances. This skill creates no mail draft, sends no native processor reminder and creates no payment link.

Read `tone-matching.md` and `../shared/voice-profile.md`. An AR CSV plus payment exports supports the same preparation; disclose their cut-off and any remaining settlement gaps.
