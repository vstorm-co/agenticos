# Native integration operations

Each product operation has one `integration.<product>.<operation>` node. The
operation service, credentials and endpoint declaration are shared with the
agent capability. Personal accounts resolve as the execution principal and are
refused in public workflows. Organization accounts are checked against the
execution organization. Writes have no automatic retry guarantee: a timeout
may mean the provider already committed the operation. Use a human approval step
before a write when the workflow needs review.
