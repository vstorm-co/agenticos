> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Contact and CRM evidence

For accounting work, a CRM may support customer identity, contact details and a documented collection arrangement. It does not replace the ledger's invoice balance, bank settlement evidence or authorized mailbox history.

Confirm the CRM tenant and relevant client/entity before reading. When multiple CRMs are connected, use the engagement's chosen source of record for the relevant population; do not merge duplicate contacts or pipeline totals indiscriminately. A name match is a candidate, not proof of identity. Preserve source IDs and explain unresolved recipient matches.

## Upstream schema examples to verify

The pinned source compared HubSpot contacts with company associations, Salesforce Leads/Contacts/Accounts and Zoho Leads/Contacts/Accounts. Those are examples of different entity models. Inspect the actual schema for contact-to-company relationships, converted/inactive records, status picklists and email fields. No fixed Headless 360 or other connector tool sequence is assumed here.

For list/search/query reads, use the supported scoped operation rather than treating a record-by-ID tool as a search endpoint. Follow current query grammar; adding a permissive filter solely to satisfy an example can accidentally widen scope.

## Dates and missing fields

A null last-activity date means the source does not establish activity, not that the customer was never contacted. Identical created-at timestamps can indicate a bulk import; do not infer relationship age from them. Use authorized mailbox or transaction evidence where relevant and disclose any gap.

## Handoff

Return verified contact details only in the restricted review package that needs them. Do not update CRM records, log activities or create tasks from this skill. An invoice reminder remains a draft regardless of whether a CRM or mailbox connector is present.
