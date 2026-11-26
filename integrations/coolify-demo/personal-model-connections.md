# Personal model connections

Personal connections let a signed-in person power an existing AgenticOS agent
with their own Anthropic API key or OpenAI API key. The
agent keeps its instructions, tools, approvals and budget controls. Select a
saved personal model from the chat model picker or the agent's model settings.

## Connect an account's API key

1. Open **Settings → AI connections** in the selected organization.
2. Choose **Anthropic API** or **OpenAI API** and store a key for that account.
3. Choose a model from the provider catalog, or enter an available model ID.
4. Select that saved personal model in the existing agent or chat model picker.

Saving a connection requires `secrets:edit`; creating a model profile requires
`connections:manage`. The screen explains missing permissions and enables
personal setup only when the server advertises support for that provider.

Saving a credential does not make an inference request. The interface reports a
saved, untested connection until the person uses it. Provider availability,
account entitlements and remaining credit are not established by storing a key.
Model requests use the provider's billing and limits.

The connection is stored in the existing encrypted vault. The key is not returned
by list or read endpoints. **Manage connections in vault** opens the existing
credential controls for rotation or deletion. Deleting a credential makes its
models unavailable; reconnect or deliberately choose another model to resume.

## Use eligible Claude subscription API credits

Anthropic documents monthly API credits for eligible Claude plans. Claim them in
Claude billing settings by linking the intended Claude Console organization,
then create an API key in that Console organization and connect it here.

All keys and workspaces in the linked Console organization share its credit
balance. Included credits are spent before purchased credits. The provider's
workspace spend limit can cap spending; AgenticOS does not verify whether a
particular request is covered by an included or purchased credit.

See the current [Anthropic API credit instructions](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers)
for eligibility, claiming, expiry and billing details.

## ChatGPT subscription sign-in

The personal-connection screen leaves ChatGPT subscription sign-in
unavailable. The dependency used by the existing legacy organization Codex flow
does not implement the current Sign in with ChatGPT application registration and
public inference contract. The new personal connection API rejects that legacy
credential kind before exchanging a sign-in callback.

An implementation of ChatGPT account sign-in needs the provider's supported application
grant for this deployment, validated state and tokens, protected and serialized
refreshes, and the documented model and inference API. See OpenAI's
[Sign in with ChatGPT overview](https://developers.openai.com/siwc/token-sharing-open-source)
and [models and inference contract](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference).

## Ownership and runtime behavior

For API connections, the vault secret owns the usage restriction. `usage_scope` is `organization` by
default for existing and ordinary new credentials. A new personal API connection
sets `usage_scope: personal` and `visibility: private`, with the authenticated
person as its owner. The usage scope is immutable.

Personal use is limited to a direct, authenticated owner context. An organization
role or resource share cannot lend the credential to another person. API-key
callers, publisher fallback, scheduled or event-driven creator contexts, channels
and background routines cannot use it. All workflow execution is excluded,
including a private workflow started by the owner, scheduled workflows and agent
runs nested under a workflow dispatch. These workflows can continue to use
organization API credentials. Fallback models are checked by the same rule.
Shared credential readers refuse personal secrets before decryption.

Administrator impersonation cannot use the impersonated person's personal
connection. The restriction is captured before model resolution and retained
after an approval pause. A permitted interactive run resumes with its original
owner's model identity, including delegate and reviewer models; the approver's
connection is never substituted. Workflow origin is also retained after a pause,
so approving a workflow cannot enable personal model use. Public workflows keep
their public origin; private workflows remain private while carrying the separate
workflow restriction.

Model profiles retain their personal owner independently of the referenced
credential. Disconnecting a key preserves that ownership and leaves the model
unavailable until the owner reconnects it. A picker binds the exact chosen secret,
so creating a personal model cannot silently reuse an organization model with a
different credential. Changing between personal and organization usage creates a
separate model profile.

The migration adds the usage scope without changing existing rows' behavior.
Account deletion removes the person's personal vault credentials instead of promoting
them into organization credentials. Downgrading across this migration requires
removing personal connections first, so a downgrade cannot discard their usage
restriction while retaining a spendable key.

## Verification and deployment

Run the focused personal-connection tests and the affected secret, model-profile,
sharing and provider-key regressions. Validate migration upgrade, downgrade and
schema parity against a disposable PostgreSQL/pgvector database. Frontend checks
cover permission gates, explicit credential selection and the saved-connection
form without making paid model requests.

Deploy the matching frontend and backend together, applying the additive database
migration before replacing API and worker containers. Keep the existing database,
cache and uploaded-media volumes. A UI-only deployment cannot enforce personal
credential ownership.
