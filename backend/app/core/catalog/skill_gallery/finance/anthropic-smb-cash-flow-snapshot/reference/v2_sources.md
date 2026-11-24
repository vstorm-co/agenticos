> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Forecast source mapping and reconciliation

Choose sources for evidence, not by brand. Confirm account/entity, production context, period, currency and source of record before reading. Independent scoped reads may run together when supported. The source examples named MYOB, NetSuite, QuickBooks, Xero, Zoho Books, Shopify, PayPal, Stripe, Square, Ramp and payroll tools; current tool schemas determine what each connection can actually return.

| Forecast input | Evidence and treatment |
|---|---|
| Opening cash | Bank/treasury balances with a common as-of date; reconcile ledger cash and classify restricted/pending funds. |
| AR | Open invoice balances, due dates, currencies and credits; match recent settlements before projecting receipts. |
| AP | Actual unpaid bills, due dates, disputes and eligible credits. Purchase orders are commitments, not interchangeable bill balances. |
| Fixed commitments | Supported rent, payroll, debt service, tax and subscription dates/amounts; deduplicate against AP. |
| Commerce/processor inflows | Expected net payout dates/amounts, fees, reserves and refunds; orders alone do not establish available cash. |
| Unposted card/expense obligations | Confirm settlement status and the cash-payment date; add only the portion not already counted through the ledger or card payable. |
| Payroll | Verified pay date and expected net cash outflow plus applicable employer remittances; reconcile differences without changing payroll. |
| Uploaded data | Confirm header mapping, signs, population, date cut-off and completeness against a control total. |

## Two ledgers or overlapping feeds

Choose a source of record for each balance. Read a secondary system only for unique supporting detail and reconcile differences. Do not add the same bank balance, invoice, card charge or payout twice because it appears in more than one system. Keep source IDs and reconciliation status in the detail schedule.

## Missing cash or payout evidence

If opening cash is unavailable, request a dated bank balance or produce net movement only. Do not assume any named ledger lacks cash endpoints universally. If a commerce connection returns orders but not payouts, obtain a payout export or label an owner-provided timing assumption. Never derive a settlement date from another store's usual practice.

## Recurrence and late expenses

Identify repeated expenses as candidate commitments, then confirm their amounts/dates and whether existing bills already capture them. Unsubmitted expenses and pending card settlements can matter, but an expense incurred date is not necessarily its bank payment date. State what was added, why and which duplicate check was performed.

## Source line in the output

List accounts and report periods actually read, source cut-offs and unavailable populations. For example: “Ledger AR/AP through 31 March, bank balance at 31 March and processor payout export through 2 April; payroll amount remains unconfirmed.” A missing source is a named uncertainty, not zero future cash flow.

Scenario ranges come from stated receipt/payment assumptions. They are not statistical confidence bounds unless a suitable validated model has actually been used and explained.
