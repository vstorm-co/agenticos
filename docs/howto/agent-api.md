---
title: "Call an agent from your own application"
description: "Authenticate, send the organization header and run a published agent over HTTP, then read the same error envelope, budget and rate limit every other surface gets."
---

# Call an agent from your own application

Call a published agent the same way the console, Slack and every other surface do: one authenticated `POST` that goes through the same runner, the same budget check and the same approval gate. This page walks the [HTTP API](../api.md) with a small agent and pastes real, trimmed responses from it. This is a procedure to run, with one recorded run as a reference.

## What you need

- A [running installation](../install.md) with a model profile, and a member account to sign in as.
- A published agent with no capability that needs an account you do not have — the recorded run below uses one with no capabilities at all, so nothing here depends on a sandbox, a collection or an MCP connection.

## Build the agent

Create an agent in **Agents → New agent**, select your model profile, leave the Toolbox empty, set a small budget and step limit, and set short instructions:

```text
You are a small support assistant reachable over the HTTP API.
Answer briefly, in two or three sentences.
If asked something you cannot know, say so plainly rather than guessing.
```

**Publish** it and copy its id from the URL or from `GET /agents`.

## Authenticate and run it

Sign in for an access token, then call the run endpoint with it and the organization header:

```bash
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -d "username=$EMAIL&password=$PASSWORD" | jq -r .access_token)

curl -s -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "In one sentence, what is a model profile?"}'
```

```python
import httpx

login = httpx.post(f"{BASE}/api/v1/auth/login",
                    data={"username": EMAIL, "password": PASSWORD})
token = login.json()["access_token"]

resp = httpx.post(
    f"{BASE}/api/v1/agents/{AGENT_ID}/run",
    headers={"Authorization": f"Bearer {token}", "X-Organization-Id": ORG_ID},
    json={"prompt": "In one sentence, what is a model profile?"},
)
resp.raise_for_status()
print(resp.json()["output"])
```

`X-Organization-Id` decides which tenant the call runs in — see [the organization header](../api.md#the-organization-header). An `X-API-Key` header works the same way for a service with no person behind it; a member's JWT is what the two calls above use.

## Stream it instead

`ws://…/api/v1/ws/agent` is the same authenticated socket the console's own chat uses, with the token in the subprotocol (`access_token.<JWT>` and `chat`) rather than a header, because a browser's `WebSocket` cannot set one. A frame carries `message`, `agent_id` and an optional `conversation_id`; the socket answers with `text_delta` events as the model writes, `tool_call` and `tool_result` for each step, `tool_approval_required` if one parks, and `complete` with the run's usage at the end. See [streaming](../api.md#streaming).

## Handle errors, budgets and rate limits

Every refusal comes back as the same envelope, `error.code`, `error.message` and `error.details`:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "prompt: Field required",
  "details": {"fields": [{"field": "prompt", "message": "Field required"}]}}}
```

A run this endpoint accepts still goes through governance: the [budget](../governance.md#budgets) is checked before the model request and the run fails rather than overspending, and a gated tool [parks for approval](../governance.md#approvals) exactly as it would in chat — an API caller cannot skip either. The route itself carries a rate limit rather than a permission gate, keyed on the caller: 30 runs per minute by default (`RATE_LIMIT_RUN_PER_MINUTE`), refused with a message to wait rather than a queue.

## Check the result

| Check | Reference |
| --- | --- |
| A normal run | `status: "completed"`, an `output` string, `cost_usd` and token counts |
| No `Authorization` header | `401`, `www-authenticate: Bearer` |
| A wrong `X-Organization-Id` | `404`, `NOT_FOUND`, the same shape as an agent that does not exist |
| An unknown `agent_id` | `404`, naming `agent_id` in `details` |
| A body missing `prompt` | `422` (`VALIDATION_ERROR`), `details.fields` names the field |
| Two organizations, one caller | The run only ever sees the tenant named in the header for that call |

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter, agent `uc-api-demo`. `POST /run` with a real prompt answered `{"status": "completed", "cost_usd": "0.000582", "output": "A model profile is a structured description of an AI model's key characteristics, capabilities, limitations, and intended use cases."}`.

    Omitting `X-Organization-Id` did **not** refuse the call here: it fell back to the signed-in member's personal organization and ran there, rather than answering "no tenant to act in". Sending a made-up organization id came back `404` with `"Organization not found or access denied"`. Omitting `Authorization` came back `401` with `www-authenticate: Bearer`. An empty body came back `422` with `details.fields: [{"field": "prompt", "message": "Field required"}]`, matching the envelope above exactly.

## When it goes wrong

- **`404` on an agent id you know exists.** Check the organization header first — a cross-tenant read answers `404`, identical to a missing agent, on purpose.
- **`429` mid-integration test.** The run route's rate limit is per caller, not per agent; back off rather than retrying immediately.
- **A run answers but never reaches a tool you enabled.** Check Activity for a parked approval — the HTTP path parks exactly like chat, and `POST /run` does not resume itself.
- **The cost you see does not match your provider's own dashboard.** `cost_is_partial` on the response says whether the number is a floor rather than a final figure; a `true` here means part of the run could not be priced.

## Record the trial

Keep the request and response for each check, the agent version, and the model profile. A person still decides which capability a server-to-server agent may hold, whether it needs its own API key rather than a shared one, and what budget bounds it — the endpoint enforces those decisions, it does not make them.

## Next steps

For a token nobody has to refresh, use an API key instead of signing in for a JWT: [authenticating](../api.md#authenticating) covers both. For what a run's tool calls and cost look like once they land in the product, see [governance](../governance.md#budgets).
