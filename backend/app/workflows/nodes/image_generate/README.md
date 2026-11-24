# Generate image

`image.generate@1` submits one bounded image request and returns an inspected,
durable workflow file. A run uses its current principal's permission to an
organization API key for the selected provider. Personal keys, incompatible
purposes and changed credential generations do not authorize the effect.

## Configuration and input

Choose `provider`, `model` and `secret_id` from the shared server catalog. The
catalog's `workflow` metadata is the option and price contract; a model with no
workflow metadata is unavailable for this node even if it remains available to
agents. GPT Image 2 is currently excluded because its public cost estimate does
not establish the hard output bound needed for a workflow reservation.

The input contains a nonempty `prompt` of at most 16,000 characters and an optional
`reference_image` file reference. Only models advertising workflow reference
support accept that input. Its run authority, metadata, bounded bytes and image
decode are checked before submission. OpenAI workflow image requests currently
accept text only; supported Google models may accept an inspected reference.

`max_cost_usd` may tighten the run cap. The server estimate returns the required
conservative reservation and any deficit before execution. `timeout_seconds`
defaults to 180, `max_output_bytes` and `max_output_pixels` to 33,554,432, and
`filename` to `generated.png`. These values remain subject to deployment limits
and the run's deadline. Media type and dimensions come from inspected bytes.

## Durability and accounting

A committed operation fixes the request fingerprint, provider, model, credential
generation, original attempt, price basis and output UUID before a provider effect.
An exact dispatch-token transition has one winner. The SDK is restricted to one
request, no automatic retry, and one OpenAI image tool call. The node permanently
declares `retry_guarantee=none`.

An inspected result is journaled before its blob is written. The blob uses that
preassigned identity; its database file row and the operation's stored state
commit together. A cancellation or refused publication retains recoverable bytes
and the fee evidence. Collection rechecks current run, principal, claim and key
generation before exposing the file and does not make another image request.

The current-operation summary separates held, incurred and booked USD. A catalog
estimate is labelled as an estimate. OpenAI native-tool input remains held because
returned prompt text does not establish all billed input. An unused reservation is
not booked as an incurred fee. Known fees are recorded once against the original
attempt, including fees discovered after it ended; ordinary spending reports
include booked fees, while admission also accounts for unresolved holds.

An unknown submission without recoverable output requires reconciliation. It is
not silently repeated by a step retry. A whole-run retry is a distinct billable
submission and retains the earlier operation's unresolved holds.

## Deployment

`WORKFLOW_IMAGE_GENERATION_ENABLED` defaults to false. The permanent definition
keeps saved graphs readable; a disabled deployment omits new palette admission
and refuses execution. Tests use synthetic transports and local disposable data.
