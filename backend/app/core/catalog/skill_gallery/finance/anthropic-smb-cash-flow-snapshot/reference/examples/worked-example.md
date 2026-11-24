> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Worked example: dated cash and cumulative horizons

All figures below are illustrative, not live connector output. Entity A uses USD. The forecast starts after the close of 31 March 2026 with reconciled available cash of USD 31,000. No FX or restricted cash is modeled. The three disjoint buckets are 1–30 April, 1–30 May and 31 May–29 June; horizons are inclusive through those end dates.

## Input schedule

| Item | Base cash date | Receipt | Payment | Evidence/assumption |
|---|---|---:|---:|---|
| Payroll | 15 April | — | USD 22,000 | Confirmed payroll cash requirement. |
| Acme invoice | 28 April | USD 8,400 | — | Due 10 April; expected 18 days after due date. |
| BlueSky invoice | 29 April | USD 14,200 | — | Due 22 April; expected 7 days after due date. |
| Rent and software | 1 May | — | USD 3,680 | Confirmed monthly commitment. |
| Payroll | 15 May | — | USD 22,000 | Confirmed recurrence. |
| Crestwood invoice | 17 May | USD 6,000 | — | Due 5 May; expected 12 days after due date. |
| Rent and software | 1 June | — | USD 3,680 | Confirmed monthly commitment. |
| Payroll | 15 June | — | USD 22,000 | Confirmed recurrence. |

No additional sales or financing is assumed. That deliberate exclusion must be visible because it drives the later cash deficit.

## Base roll-forward

| Bucket / cumulative horizon | Bucket receipts | Bucket payments | Bucket net movement | Cumulative net movement | Closing cash |
|---|---:|---:|---:|---:|---:|
| Days 1–30 / 30 April | USD 22,600 | USD 22,000 | USD 600 | USD 600 | USD 31,600 |
| Days 31–60 / 30 May | USD 6,000 | USD 25,680 | USD -19,680 | USD -19,080 | USD 11,920 |
| Days 61–90 / 29 June | USD 0 | USD 25,680 | USD -25,680 | USD -44,760 | USD -13,760 |

Checks: total receipts USD 28,600; total payments USD 73,360; total net movement USD -44,760; opening USD 31,000 plus net USD -44,760 equals closing USD -13,760.

## Downside scenario

Assume Acme and BlueSky receipts slip to 8 and 9 May, respectively. Other rows stay unchanged. This is a timing sensitivity, not a statistical confidence interval.

| Horizon | Base closing cash | Downside closing cash | Explanation |
|---|---:|---:|---|
| 30 April | USD 31,600 | USD 9,000 | USD 22,600 of receipts moves beyond April. |
| 30 May | USD 11,920 | USD 11,920 | Both delayed receipts arrive within May. |
| 29 June | USD -13,760 | USD -13,760 | Timing catches up; total modeled receipts do not change. |

## Risk interpretation

The 15 April payroll leaves USD 9,000 in both scenarios; there is no April payroll shortfall in this example. Before the delayed receipts, the downside balance falls to USD 5,320 after the 1 May commitments. The 15 June payroll produces a projected USD 13,760 deficit because no new sales/financing beyond the listed invoices is included. Name that modeling limitation and ask for the missing future revenue or confirmed funding plan before treating the deficit as a full-business conclusion.

An XLSX version, when a runtime is available, uses Summary, Detail and Risks sheets. Keep the dated assumptions and reconciliation formulas visible. Mark the deliverable prepared for review; no payment or forecast schedule has been executed.
