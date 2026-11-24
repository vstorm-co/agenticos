# Generate video

`video.generate@1` submits one bounded video job or collects an existing durable
receipt, then returns an inspected workflow file. It uses an authorized
organization API key with the selected provider's purpose and the generation
recorded at admission.

## Configuration and input

`provider`, `model` and `secret_id` are required. The shared video catalog's
`workflow` metadata supplies supported options, effective defaults, dated rates
and reference-image eligibility. The server estimate uses the same reservation
helper as execution, without unwrapping a key or contacting a provider.

The input is a nonempty `prompt` of at most 16,000 characters and an optional
authorized, inspected `reference_image`. Configuration includes `resolution`,
`aspect_ratio`, `seconds` and `audio`; absent values resolve through the catalog.
Optional audio defaults to false. Fixed audio behavior is shown by the model;
variable-duration models reserve their maximum while leaving requested seconds
unset. The reservation covers the supported sound-on rate where audio affects
the cost. An unused maximum is never presented as generated duration or a fee.

`timeout_seconds` defaults to 180, `max_output_bytes` to 134,217,728,
`max_output_pixels` to 33,554,432, and `filename` to `generated.mp4`.
`max_cost_usd` may tighten the run cap. Actual bytes, dimensions and duration must
pass the deployment and configured inspection limits before publication.

## Submission and recovery

The operation commits its immutable request, credential, pricing and output
identity before submission. The exact dispatch-token transition has one winner.
A closed receipt contains only provider, API, model, kind and opaque identifier;
it is committed before further polling or download. Recovery with a receipt
checks that exact identity and performs collection only. It cannot fall back to
another POST. Protected download validation applies to every redirect hop.

The node's permanent `retry_guarantee=none` describes new submissions. A receipt
is separate proof that collection is safe. The existing dispatcher may requeue
that collection within its normal backoff and retry ceiling, including when the
run has no budget left for a new request. Current principal, run, claim and key
generation still have to authorize collection and file publication.

If a request may have been submitted but has no receipt, the operation becomes
unknown and retains its hold. In-place `run_again` is refused pending
reconciliation. A whole-run retry is a separately billable run and preserves the
original evidence and unresolved amounts.

An inspected output is journaled before deterministic blob storage. The file row
and stored-operation link commit in one transaction. Simultaneous collectors use
the same UUID, and an interrupted collector never deletes another collector's
committed file. Recoverable local bytes require no provider request.

## Costs and deployment

Observed or generated duration is priced from the admitted catalog snapshot and
labelled `catalog_estimate`; a reported fee is labelled `reported`. A maximum
reservation remains distinct from incurred and booked cost. Known fees survive
download, quota and authorization failures and are booked once to the original
attempt. Unresolved operations prevent retention and workflow deletion from
erasing their evidence.

`WORKFLOW_VIDEO_GENERATION_ENABLED` defaults to false. The definition remains
registered for saved graph compatibility, while disabled deployments refuse new
admission and execution. Native tests use fake providers and disposable data.
