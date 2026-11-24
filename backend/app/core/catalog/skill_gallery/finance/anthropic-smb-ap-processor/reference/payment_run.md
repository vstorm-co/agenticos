> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Payment proposal and reviewer decisions

## Separate accounting from spending

The output has two review decisions: whether the proposed bill coding is correct, and which verified obligations the owner intends to pay. This skill records neither approval as an external action. It prepares the documents for the separate operational workflow and initiates no payment, bank instruction, vendor approval or ledger import.

Illustrative review prompts are “Please review 19 proposed unpaid bills totaling USD 41,208” and, separately, “The proposed Thursday outflow is USD 22,140 across 11 bills.” An approved workpaper is not evidence that a bill was posted or a payment scheduled.

## Build the proposal

Consider overdue obligations and documented relationship risk, worthwhile early-payment discounts, invoices due within the agreed run window and later obligations to defer. Use the engagement's actual due/discount dates. A 2% discount on USD 10,000 is USD 200; show its date and eligibility rather than only a terms code.

Hold unresolved duplicates, unreadable amounts, active disputes, unverified bank changes, uncertain credits and already-paid card expenses. List every exclusion with the reason and due date so a held bill does not disappear from oversight.

Group by vendor, entity, currency and existing verified payment method. Show invoice references, gross amount, settlements, eligible credit, proposed net, intended date and review status. Credits require confirmed availability and allocation; this skill does not apply them.

## Cash awareness

Use the installed `anthropic-smb-cash-flow-snapshot` skill's same-scope output or other reconciled cash evidence to show the projected balance at the payment date and the effect on payroll/other commitments. If cash evidence is unavailable, state that affordability is not assessed. Show any proposed deferral against the cash floor and name the obligations it leaves unpaid.

## Short pays and disputes

Record proposed paid/held amounts separately and keep the remaining balance in the review aging. Draft a vendor note with invoice/line references and the factual reason; use `../shared/voice-profile.md`. The note remains unsent.

## Illustrative review package

Eleven proposed bills total USD 22,140. Two are past due, one has a USD 124 early-payment discount, and three other bills are held for quantity or readability issues. A supported cash forecast shows USD 31,400 after the proposed run, before an upcoming USD 18,900 payroll. State the forecast dates and other commitments before describing the remaining margin. Mark every value as illustrative here, and every real output “prepared — not executed.”
