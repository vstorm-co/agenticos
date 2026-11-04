# trigger.github

A workflow something happening in a GitHub repository starts: an issue opened, a
pull request merged, a push, a release. Publishing a version with this trigger
gives it its own webhook address and signing secret.

## Setting up the webhook

With **Set up the webhook for me** on and the organization's GitHub account
connected with `admin:repo_hook`, the publish registers the hook on the
repository, for the events the node names, and every later publish registers it
again so a change of repository or events reaches GitHub. Otherwise - no
account, a missing scope, a repository the account cannot reach - the publish
shows the address and the secret once, to paste into the repository's
**Settings > Webhooks** with the content type `application/json`. The trigger's
panel says which of the two it is, and **New secret** replaces the secret,
registering the hook again where the account set it up.

## Which deliveries

A delivery must carry GitHub's `X-Hub-Signature-256` under the secret and its
`X-GitHub-Delivery` id; a redelivery of the same id answers with the first run.
It starts a run only when it is for the repository named, one of the events
named and - when actions are named - one of those actions. Anything else,
GitHub's `ping` included, is answered `202` with what it was skipped for, and
starts nothing. A body over `WORKFLOW_RUN_MAX_INPUT_BYTES` is refused.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `GithubTriggerOutput` | `event`, `action`, `repository`, `sender`, `delivery_id`, and the whole `payload` |
