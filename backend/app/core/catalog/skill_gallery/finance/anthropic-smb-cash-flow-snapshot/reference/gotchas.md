> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Cash-flow validation cases

1. **Already collected invoices:** use verified open balance and matched settlements, not face value alone. Do not subtract a processor receipt twice if the ledger balance already includes it.
2. **Settlement timing:** estimate from actual matched payment/payout dates. Fees, holds, refunds, weekends and reserves can change available cash; a sales-order date is not a payout date.
3. **Ambiguous CSVs:** confirm date formats, debit/credit signs, transaction type, currency and header mapping. A column called “amount” may be gross, net or an accounting sign convention.
4. **Recurring costs:** repeated vendor/amount patterns suggest a possible commitment; confirm the schedule and exclude duplicates already represented in AP/payroll.
5. **Zero or small mean lag:** never divide by payment lag to create a presumed confidence percentage. Use explicit date/amount scenarios and name sparse evidence. Immediate settlement does not imply a universal 5% risk band.
6. **Different lag bases:** invoice-to-receipt lag belongs on invoice date; days overdue belongs on due date. Do not add the full payment term twice.
7. **Negative net movement:** multiplying a negative net by 1±percentage can reverse low/high labels and conceal gross flow risk. Recalculate receipts and outflows independently in each scenario.
8. **Opening cash and horizon arithmetic:** closing cash equals opening cash plus cumulative net movement. Separate disjoint monthly buckets from cumulative 30/60/90-day horizons. Reconcile all totals.
9. **Past transactions:** keep them as historical evidence, not future obligations. If the forecast starts 1 April, a 15 March payroll already paid is not a 15 April forecast outflow without evidence of recurrence.
10. **Intra-period shortfalls:** check cash on the actual payroll/payment date. A positive month-end balance can follow a mid-month overdraft.
11. **Scenario vs probability:** a downside scenario is a stated alternative, not a confidence interval or promise. Show the assumption that changed.
12. **Missing opening balance:** report net movements and limitations; do not infer an absolute shortfall or payroll affordability from inflow totals alone.
