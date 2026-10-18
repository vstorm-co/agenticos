#!/usr/bin/env bash
# The public API from a terminal, with no browser anywhere: sign in, issue a
# read-only organization key, call the API with it, and revoke the key on exit.
#
#   BASE=https://agenticos.example.com EMAIL=you@example.com PASSWORD=... \
#     bash docs/examples/public-api.sh
#
# ORG_ID picks the organization; without it the script uses your personal one.
# AGENT_ID, when set, also runs that agent and reads the run back, which needs a
# key with agents:run and runs:view - the script then issues one with those two.
# Needs curl and jq. See docs/api.md#without-a-browser.
set -euo pipefail

: "${BASE:?set BASE to the deployment origin, e.g. http://localhost:8000}"
: "${EMAIL:?set EMAIL}"
: "${PASSWORD:?set PASSWORD}"
API="$BASE/api/v1"

# Sign-in takes a form body, the OAuth2 password grant, not JSON.
SESSION=$(curl -fsS -X POST "$API/auth/login" \
  -d "username=$EMAIL" --data-urlencode "password=$PASSWORD" | jq -r .access_token)
as_member() { curl -sS --fail-with-body -H "Authorization: Bearer $SESSION" -H "X-Organization-Id: $ORG_ID" "$@"; }

if [[ -z "${ORG_ID:-}" ]]; then
  ORG_ID=$(curl -fsS "$API/orgs" -H "Authorization: Bearer $SESSION" \
    | jq -r '[.items[] | select(.is_personal)][0].id')
fi

if [[ -n "${AGENT_ID:-}" ]]; then
  SCOPES='["agents:view", "agents:run", "runs:view"]'
else
  SCOPES=$(as_member "$API/api-keys/scopes" | jq -c '.presets[] | select(.id == "read_only") | .scopes')
fi

# Key management is session-only by design, so a leaked key cannot mint another.
CREATED=$(as_member -X POST "$API/api-keys" -H "Content-Type: application/json" \
  -d "{\"name\": \"public-api example\", \"scopes\": $SCOPES}")
KEY_ID=$(jq -r .id <<<"$CREATED")
KEY=$(jq -r .key <<<"$CREATED")
trap 'as_member -X DELETE "$API/api-keys/$KEY_ID" >/dev/null && echo "revoked key $KEY_ID"' EXIT
echo "issued key $(jq -r .prefix <<<"$CREATED") with $SCOPES"

# From here on only the key is used: no session, no organization header.
as_key() { curl -sS --fail-with-body -H "Authorization: Bearer $KEY" "$@"; }

echo "permissions: $(as_key "$API/me/permissions" | jq -c '[.permissions[].permission]')"
echo "agents:      $(as_key "$API/agents?limit=5" | jq -r '[.items[].name] | join(", ")')"
echo "runs:        $(as_key "$API/runs?limit=5" | jq -r '.total')"

# A route outside the key's permissions is refused with the error envelope.
REFUSED=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API/agents" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{}')
echo "creating an agent with this key answers $REFUSED"

if [[ -n "${AGENT_ID:-}" ]]; then
  # The first call opens a conversation; the second continues it, and the agent
  # reads what was said before (docs/api.md#running-an-agent).
  ANSWER=$(as_key -X POST "$API/agents/$AGENT_ID/run" -H "Content-Type: application/json" \
    -d '{"prompt": "Remember the word: heron. Reply with one word: ready"}') \
    || { echo "run refused: $ANSWER" >&2; exit 1; }
  echo "answer:      $(jq -r .output <<<"$ANSWER")"
  as_key "$API/runs/$(jq -r .run_id <<<"$ANSWER")" | jq -c '{status, input_tokens, output_tokens, cost_usd}'
  CONVERSATION=$(jq -r .conversation_id <<<"$ANSWER")
  AGAIN=$(as_key -X POST "$API/agents/$AGENT_ID/run" -H "Content-Type: application/json" \
    -d "{\"prompt\": \"Which word did I ask you to remember?\", \"conversation_id\": \"$CONVERSATION\"}") \
    || { echo "run refused: $AGAIN" >&2; exit 1; }
  echo "remembered:  $(jq -r .output <<<"$AGAIN")"
  echo "turns:       $(as_key "$API/conversations/$CONVERSATION/transcript" | jq -r '.total')"
fi
