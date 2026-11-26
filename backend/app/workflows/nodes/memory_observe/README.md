# Record memory observation

This action uses the selected workflow entry's authenticated delivery. Configure a
business object key and the one property the workflow may record. A Gmail trigger
needs a verified full sender address and a deadline line. A signed Webhook trigger
can carry a typed observation for that same configured key and property. Draft
runs show a preview. Route the `changed` output through the existing workflow
conditions and notification step.
