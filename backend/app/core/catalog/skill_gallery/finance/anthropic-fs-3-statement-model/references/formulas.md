<!-- Modified for t3OS on 2026-11-10; derived from anthropics/financial-services at 60565064557ca77b12f62aa7877f365d111c129d. See the skill's SOURCE.md and LICENSE.txt. -->

# Formula Reference

Use these linkages as model controls. Adapt line definitions, signs, tax rules, and classification to the engagement's accounting framework, entity, jurisdiction, and period. Preserve source precision and use an agreed tolerance; no unexplained plug may be used to force a balance. Missing inputs and unverified tax assumptions remain visible.

## Core linkages

| Linkage | Check |
|---|---|
| Balance sheet | Assets - Liabilities - Equity = 0 |
| Net income | The income statement's relevant net income links to retained earnings and, where the indirect method starts with that figure, operating cash flow |
| Cash | Beginning cash + CFO + CFI + CFF + applicable FX or other cash reconciliation movements = Ending cash |
| Cash tie-out | Ending cash and cash equivalents in the cash-flow statement reconcile to the balance sheet's corresponding amounts, with restricted cash and scope differences explained |
| Monthly to annual | Final monthly closing cash agrees to the corresponding annual closing cash; sum monthly flows, not monthly balances |
| Retained earnings | Beginning RE + Net income - Dividends +/- documented direct RE adjustments = Ending RE |
| Equity issuance | Cash issuance proceeds reconcile to the cash-issuance component of the equity roll-forward, with issue costs and noncash movements separately explained |

## Gross profit and margins

Recognize revenue and deductions under the applicable accounting policy. Where the presentation separates returns, allowances, and discounts, reconcile gross revenue to reported net revenue; use the reported revenue basis consistently.

```
Gross Profit        = Net Revenue - Cost of Revenue
Gross Margin        = Gross Profit / Net Revenue
EBITDA              = EBIT + D&A included in EBIT
EBITDA Margin       = EBITDA / Net Revenue
EBIT Margin         = EBIT / Net Revenue
Net Income Margin   = Net Income / Net Revenue
```

Avoid double-counting D&A, SBC, and other costs that are already allocated into cost of sales or operating expenses. Label adjusted EBITDA and reconcile every adjustment to the reported measure. A zero or inappropriate denominator makes a ratio not meaningful, not zero.

## Credit metrics

Use the exact covenant or agreed analytical definition, including debt, leases, cash restrictions, EBITDA adjustments, and averaging conventions.

```
Total Debt           = Relevant current debt + relevant long-term debt
Net Debt             = Total Debt - eligible cash
Debt / EBITDA        = Relevant Debt / defined EBITDA
Interest Coverage    = Defined earnings measure / defined interest expense
Debt / Total Capital = Defined Debt / (Defined Debt + Defined Equity)
Current Ratio        = Current Assets / Current Liabilities
Quick Ratio          = Eligible liquid current assets / Current Liabilities
```

Do not assume all current assets except inventory are quick assets; prepaid expenses and other items may be ineligible. Retain units, sign conventions, and the time basis. Negative or near-zero denominators need an explicit interpretation.

## Forecast drivers

Percent-of-revenue assumptions are one supported approach:

```
Forecast Expense = Forecast Revenue x approved expense-rate assumption
```

Use operating drivers such as headcount, price, volume, utilization, or fixed and variable cost where they better represent the business. Keep assumptions in identified input cells and derived results as formulas; document the basis and source. SBC must be classified consistently across the income statement, equity, and cash-flow schedules.

## Working capital

```
Beginning AR + Credit sales - Collections +/- Other movements = Ending AR
Beginning Inventory + Purchases - Cost recognized +/- Other movements = Ending Inventory
Beginning AP + Relevant credit purchases - Payments +/- Other movements = Ending AP
Operating NWC = Defined operating current assets - Defined operating current liabilities
Change in NWC = Current NWC - Prior NWC
```

Reconcile write-offs, taxes, reclassifications, FX, and scope changes. Use a documented driver to forecast collections or purchases; do not hide an unexplained difference in a balancing plug.

```
DSO = Relevant average AR / period credit sales x days in period
DIO = Relevant average inventory / period cost of sales x days in period
DPO = Relevant average AP / period purchases (or disclosed cost-of-sales proxy) x days in period
```

Use the same period and basis in each ratio. Closing-balance approximations and cost-of-sales proxies must be labelled; 365 days is not appropriate for every period.

## D&A schedule

```
Beginning gross PP&E
+ Additions
- Disposals at gross cost
+/- Transfers, FX, and other supported movements
= Ending gross PP&E

Beginning accumulated depreciation
+ Period depreciation
- Accumulated depreciation on disposals
+/- Transfers, FX, and other supported movements
= Ending accumulated depreciation

Net PP&E = Gross PP&E - Accumulated depreciation - applicable impairment
```

Use the applicable useful life, residual value, in-service timing, depreciation method, and impairment policy. Reconcile cash capital expenditure to asset additions and capital creditors where they differ. Intangibles, leases, and construction balances may require separate schedules.

## Debt and interest

```
Beginning debt + Drawdowns - Principal repayments +/- Other supported movements = Ending debt
Cash interest = Applicable principal basis x rate x contractual day fraction
```

Trace noncash accretion, financing costs, FX, conversions, and current/noncurrent classification. Distinguish cash interest from accounting interest expense. Resolve circularity with a documented schedule method or an actual calculation engine; never claim iteration occurred when it did not.

## Retained earnings and equity

```
Beginning retained earnings
+ Net income attributable to the relevant equity holders
- Dividends or distributions charged to retained earnings
+/- Supported direct retained-earnings adjustments
= Ending retained earnings
```

Do not add SBC to retained earnings after net income. Equity-settled compensation normally affects its specified equity account, while its expense is already reflected in net income; treatment must follow the applicable award and accounting policy. Reconcile common stock, APIC or equivalent reserves, treasury shares, other comprehensive income, and noncontrolling interests separately. A cash issuance cannot explain every change in total equity.

## Tax losses and deferred tax

This schedule is parameterized by jurisdiction, legal entity, loss vintage, and effective tax year. Obtain approved rules or a tax-specialist input for loss generation, utilization, expiry, ownership changes, carryback, and group treatment.

```
Beginning eligible tax losses
+ Qualifying tax losses generated or transferred under applicable rules
- Losses utilized
- Losses expired or otherwise restricted
+/- Supported corrections
= Ending eligible tax losses

Accounting profit before tax
+/- Applicable book-to-tax adjustments
= Taxable profit or loss before loss relief

Permitted loss relief = Amount supported by available eligible losses and applicable restrictions
Taxable base after relief = Taxable base before relief - Permitted relief, as governed by local rules
```

Book EBT is not automatically taxable income, and the first forecast year is not proof of a zero opening tax-loss balance. Do not apply a universal 80% cap or invent loss balances. Track current tax expense, tax payable, instalments, credits, refunds, and minimum or other taxes separately as required.

Recognize deferred tax assets and liabilities using the governing framework, applicable rates, and recognition and recoverability requirements. A tax loss does not automatically create a fully recognized asset. Reconcile deferred-tax movements through profit or loss, equity or OCI, acquisitions, FX, and other components; total balance movement is not automatically a profit-or-loss or cash-flow adjustment.

```
Total tax expense = Current tax expense + Deferred tax expense (benefit is negative)
Net income = Accounting profit before tax - Total tax expense
```

NOL utilization reduces the relevant tax base; it is not an additional expense deducted from accounting profit to calculate net income.

## Balance-sheet structure

Map the actual chart of accounts and framework presentation into cash, receivables, inventory, other assets, PP&E, deferred tax, payables, debt, other liabilities, and the components of equity. Include all material balances; a simplified example must not silently omit an actual balance.

```
Total Assets - Total Liabilities - Total Equity = 0
```

Tie every modeled balance to a source or roll-forward and separate current from noncurrent items under the applicable presentation rules.

## Cash-flow structure

For an indirect operating cash-flow presentation, reconcile the actual starting profit measure to cash:

```
Starting profit measure
+/- Noncash profit-or-loss adjustments (including relevant D&A, SBC, impairment, deferred tax)
+/- Items classified in investing or financing
- Increases / + decreases in relevant operating assets
+ Increases / - decreases in relevant operating liabilities
+/- Other required reconciling items
= Operating cash flow

Investing cash inflows - Investing cash outflows = Investing cash flow
Financing cash inflows - Financing cash outflows = Financing cash flow
```

A deferred-tax asset increase is not itself a cash payment; reverse only the relevant noncash profit-or-loss component and reconcile the rest. Classify interest, taxes, dividends, leases, restricted cash, and noncash transactions under the chosen framework and policy. Exclude noncash asset and liability movements from cash-flow changes or reconcile them explicitly.

## Income-statement structure

```
Recognized revenue
- Cost of revenue
= Gross profit
- Operating expenses
+/- Other operating items
= Operating profit
+/- Financing and other nonoperating items
= Accounting profit before tax
- Current tax expense
- Deferred tax expense (or + benefit)
= Net income
```

Place costs only once and reconcile EBITDA separately when needed. Do not replace accounting profit with taxable income or deduct tax-loss utilization as an expense.

## Model checks

- Balance sheet: assets less liabilities and equity equals zero within the agreed numerical tolerance.
- Cash: beginning balance, cash flows, and other reconciliation movements explain ending cash.
- Retained earnings: opening RE, net income, distributions, and documented direct adjustments explain closing RE.
- Equity: cash issuance, SBC, noncash movements, distributions, and other changes reconcile by account.
- Debt, fixed assets, working capital, and deferred tax tie to their schedules and accounting statements.
- Tax losses: available balances, restrictions, utilization, and closing balances agree to approved assumptions and evidence.
- Scenario changes: inputs drive formulas consistently; a claimed scenario ordering must be justified rather than forced.
- Formula integrity: no unexplained error cells, external links, hardcoded derived results, or hidden balancing plugs.
- Recalculation: report the actual engine, checked outputs, and any unavailable calculation or rendering step.
