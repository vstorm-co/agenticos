> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Accounting report validation: upstream QuickBooks examples

These are failure patterns observed by the pinned upstream source for a particular connector snapshot. They are not claims that QuickBooks or every current connector has these defects. Inspect the actual schema, report metadata and returned evidence before deciding which pattern applies.

## 1. A constrained population is not the whole book

Top-N aging, vendor filters, due-date ranges and pagination can make a subtotal appear complete. Use bounded detail reads for relevant transactions and a separately reconciled full control total for AR/AP. Label the slice and account for omitted pages. Do not request an unbounded report merely because the summary is incomplete.

## 2. Summary fields disagree with rows

The source saw zero expenses or 100% margin summary fields alongside nonzero expense rows. Recompute complete detail, separate COGS from operating expenses and tie to the trial balance. If costs were never classified into COGS, say the split is unavailable; do not infer a valid gross margin from a default zero.

## 3. Parent totals double-count children

Some reports contain both customer parents/subtotals and child/detail rows. Inspect row metadata and use one aggregation level. Tie the selected total to the report control; never add both levels.

## 4. Returned periods differ from requested dates

Inspect report period metadata and sample transaction dates. The upstream example found a product report that ignored requested dates. If the returned population does not establish the requested period, label it unusable for period comparisons and use a supported source instead. Identical periods do not prove zero growth.

## 5. Product detail covers only part of revenue

Reconcile product/customer breakdown totals to the same-period ledger revenue before interpreting mix or growth. State the coverage percentage and exclusions. A channel subtotal cannot explain a whole-company result without a reconciliation.

## 6. Net aging hides credits

Inspect invoices, credit notes, returns and payments separately. A negative bucket can indicate a credit, and a net total can hide gross overdue amounts. Verify credit eligibility, currency, entity and prior application; show gross, credit and proposed net separately. A partial credit does not eliminate the remaining obligation. Reconcile balance-sheet AR/AP to complete subledger support and explain timing/classification differences.

Use current detail/filter schemas that preserve credit rows; do not blindly reuse a past tool name, unset parameter or prohibited query. No credit is applied by this skill.

## 7. Payroll readiness and employee lists disagree

Record both evidence sources when readiness flags, employee counts or payroll status conflict. An employee list does not itself establish a calculated/approved payroll. Do not infer payroll is ready, edit employees or stage a run to work around the conflict. Mark forecast amounts as unverified until the discrepancy is resolved by the owner or payroll reviewer.

## Capability boundary

Inspect the current read surface. Historical connector restrictions do not establish product-wide limitations. This preparation pack never creates bills/vendors, records expenses, changes payroll or stages work in another system as a workaround.
