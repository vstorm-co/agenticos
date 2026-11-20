> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Connector schema and result checks

The upstream source recorded particular connector names and payloads. t3OS installs none of those connections with this skill. Use the currently exposed tool schemas, authorized account and engagement source of record. Do not copy an upstream tool name or argument blindly.

## Before any read

1. Confirm the tool is actually available and authorized for the target account, entity and production/sandbox context.
2. Read the exact operation and parameter schema, including date formats, status enums, entity identifiers, pagination and result limits.
3. Use a bounded read for the required evidence. Preserve query parameters and data cut-off in the workpaper.
4. Validate returned population, currency, dates and control totals. A successful response does not prove the query covered the intended population.

## Snapshot-derived checks

| Source pattern | Check to carry into the current schema |
|---|---|
| Processor unpaid-invoice lists | An unpaid flag can coexist with cancellation or void status. Verify lifecycle status, not just balance/payment status. |
| Processor invoice identifiers | An external invoice number may differ from the ledger number; inspect explicit metadata or verified mappings and keep uncertain matches unresolved. |
| Customer-detail joins | Some invoice rows expose only a customer ID. Read the matching authorized customer record before attributing a recipient or business name. |
| Date filters | Some APIs distinguish offset forms, inclusive/end-exclusive boundaries and created/settled/due dates. Follow the active schema and inspect returned dates. |
| Payroll/time data | Distinguish native shifts, third-party timesheets, payroll dates and unprocessed periods. Empty rosters and readiness flags can disagree; record the exception without changing payroll. |
| CRM reads | ID retrieval differs from search/list/query operations. Discover the supported read and field names; do not assume a product's API is exposed as individual tools. |
| QuickBooks report summaries | Compare summary fields to detailed rows, pagination, report periods and credit treatment before using the total; see `quickbooks-report-traps.md`. |
| Mail labels | Verify whether the exposed search uses a label ID or display-name expression and cross-check empty results; see `gmail-inbox-traps.md`. |

No write-call recipe is provided here. Payroll updates, time recording, CRM dispatch writes, bill creation, approvals and payment-link creation are outside the preparation workflow, even if such tools are connected. Where the required read is unavailable, ask for an appropriately scoped export and name the resulting limitation.
