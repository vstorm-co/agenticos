> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Absent is not zero

Missing, empty, paginated and contradictory data describe the evidence, not necessarily the business. Record the distinction before using a figure in an accounting conclusion.

## Checks before reporting a total

1. Identify the population, entity, period, currency, pagination and filters. A top-N or date-limited result is a slice, not a whole-book total. Reconcile it to a complete control total or label it partial.
2. Recalculate from complete detail where available and compare it to the summary. A disagreement is an exception to investigate, not permission to silently choose the more convenient figure. Do not sum subtotal rows and leaf rows together.
3. Distinguish a documented zero from a missing/null/defaulted field. An implausible zero is a reason to seek evidence; it is not automatically missing, and missing is not automatically zero.
4. A missing activity or payment date means history is unknown or unrecorded. Do not infer that nothing happened. A bulk-import date may not be a relationship or transaction date.
5. Compare historical-event timestamps to the as-of date. A future timestamp on a supposedly completed event needs explanation; a future due date, scheduled payment or forecast date is legitimate and must not be discarded for being future.
6. Cross-check an empty search against a known count, record or source report before concluding the population is empty. Confirm query semantics, period and permissions.
7. Keep available cash, pending balances, restricted funds and expected payouts distinct. A processor's zero available balance does not establish that pending funds are zero.

## Illustrative failures

| Evidence issue | Unsupported conclusion | Reviewable result |
|---|---|---|
| Top-ten aging rows total USD 25,907; full control total is USD 37,055 | Total receivables are USD 25,907 | Label the slice and reconcile the missing USD 11,148. |
| P&L summary says expenses are zero while rows contain expenses | Margin is 100% | Recalculate complete rows and report the contradiction. |
| Search returns no messages but the scoped label count is nonzero | There are no invoices | Verify the query and attachment coverage. |
| Revenue field is null or defaulted to zero | The business has no revenue | State that this source does not establish revenue. |
| A source is inaccessible | Nothing is owed there | Name the source and missing population. |

Tell the reviewer which figure is supported, what remains incomplete and what source would resolve it. See `quickbooks-report-traps.md` and `gmail-inbox-traps.md` for connector-snapshot examples.
