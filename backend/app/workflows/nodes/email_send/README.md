# email.send

Sends a plain-text email to up to ten addresses, one copy each, from the
deployment's own sender and email provider. It is for people outside the
organization - a lead, a customer; `notification.send` reaches members through
their own preferences. `reply_to` sends replies somewhere other than the
deployment's reply address.

The output lists the addresses the provider accepted, and `delivered` is false
when the provider only logs mail. A refused copy fails the step with what was
already sent named; mail has no idempotency key, so a retry sends again.
