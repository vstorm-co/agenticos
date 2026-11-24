# Connector categories in this t3OS adaptation

The upstream finance plugin describes operations by category. This skill ships no MCP connection and no credentials. Resolve categories through the agent's actual connections and inspect the exact exposed tool schema before a read. Use supplied exports when the required read is not available.

| Category | Required evidence | How to use it here |
|---|---|---|
| Accounting / ERP | Entity-scoped trial balance, GL, subledger, chart of accounts and period status | Read and prepare proposed entries; no ledger posting or payment tools are authorized by this skill. |
| Data warehouse | Documented tables, entity keys, period filters, currency and reconciled balances | Use authorized read-only queries; reconcile to the source ledger. |
| Files / office documents | Source workbook/PDF and stable page or row references | Read uploaded or connected files in the authorized engagement; preserve evidence references. |
| Email / chat | Named mailbox/channel and the engagement's evidence or requested draft | Read only the authorized scope; prepare messages for review without sending. |
| Analytics | Defined metrics, source period, currency and exclusions | Use reported data only after reconciliation; separate forecasts from actuals. |

The upstream plugin's example server roster and tool placeholders are not installed by this adaptation. References elsewhere to a product are examples rather than a promise that its connector exposes a particular endpoint. Use the current tool contract and the engagement's source-of-record decision.
