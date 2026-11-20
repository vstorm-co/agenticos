# Request a secret

An agent that needs a credential it was not given - an API key, a token -
asks for it with `request_secret`, naming the secret and what it is for.
The run parks on the call and the person supplies the value through the
card the request draws. The value is sealed into the vault from the card
and the run resumes. The model never sees the value: not as a tool
argument, not as a tool result, not in the transcript.

## Why a card, not a chat message

A value pasted into chat would land in the transcript, the run record and
the model context - every place a secret must never be. The card posts to
the fulfil endpoint, which seals the value straight into
`organization_secrets` and keeps only the created secret's id, name and
hint on the request row. What the model reads back on resume names the
stored secret and its hint, never the value.

## What declining does

Declining ends the run failed, with the refusal as its error - a clear
failed report, not a silent stall and not a resumed model left to ask
again. An unanswered request expires with the question window (24 hours),
settled like an unanswered question.

## What it deliberately does not do

- It does not change how existing credentials are stored, and it does not
  touch Composio credentials. Storage reuses `OrganizationSecretService`
  and the vault's `ApiKeySecret` shape as-is.
- It does not hand the stored secret to the agent. A later capability
  binding can reference the stored secret by id, the way every other
  secret is referenced; this tool only gets it stored.
- It does not let the agent choose the storage: the name the agent gives
  is the name it is stored under, and a name that is already taken is
  refused rather than silently overwritten or suffixed.
