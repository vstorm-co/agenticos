# email.send

Sends a plain-text email to up to ten addresses, one copy each, from the
deployment's own sender and email provider. It is for people outside the
organization - a lead, a customer; `notification.send` reaches members through
their own preferences. `reply_to` sends replies somewhere other than the
deployment's reply address.

The output lists the addresses the provider accepted, and `delivered` is false
when the provider only logs mail. A refused copy fails the step with what was
already sent named; mail has no idempotency key, so a retry sends again.

Delivering providers reserve each unique recipient against shared Redis allowances before sending the whole batch: `WORKFLOW_EMAIL_MAX_PER_PRINCIPAL_PER_HOUR` (100), `WORKFLOW_EMAIL_MAX_PER_ORG_PER_HOUR` (500) and `WORKFLOW_EMAIL_MAX_PER_DEPLOYMENT_PER_HOUR` (1000). The principal limit spans keys and organizations of the same issuer. Fixed one-hour windows span runs and workers; their boundary can admit twice the allowance. Exhaustion gives `EMAIL_DELIVERY_LIMIT`; unavailable counters give `EMAIL_ALLOWANCE_UNAVAILABLE`, with no send. Reservations are conservative and not refunded after partial reservation, provider failure or cancellation. Log-only providers consume no delivery allowance. Set deployment capacity below the relay quota to leave transactional-mail headroom.
