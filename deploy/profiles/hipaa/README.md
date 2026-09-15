# The HIPAA deployment profile

An opinionated configuration for running AgenticOS inside an environment that
has to satisfy HIPAA's **technical** safeguards, §164.312 — plus a command that
proves a running deployment matches it.

```bash
uv run agenticos cmd doctor --profile hipaa
```

One row per control, naming the setting that satisfies it or the one that does
not, and a non-zero exit on any failure so a client's own CI can gate on it.

## What this is not

**Not a certification, and not a compliance claim.** HHS certifies no software
and OCR recognises no private certification. What this answers is the question a
security review actually asks: *can we run this inside our compliant
environment, and can you prove it.*

**Not the whole of HIPAA.** The profile answers §164.312 and only that.
Administrative safeguards (§164.308 — risk analysis, workforce training, a
sanction policy, a contingency plan, business associate agreements) and physical
safeguards (§164.310) belong to the operator and always will.

**Not a business associate agreement.** A client running this on their own
infrastructure gets software; nobody here touches their PHI, and no agreement is
needed. A deployment somebody else operates for them makes that operator a
business associate, which is a contract rather than a configuration flag.

## Files

| | |
|---|---|
| `docker-compose.hipaa.yml` | An overlay over the repository's `docker-compose.yml`. It sets the transport, sign-in and observability settings the profile asks for, and refuses to start without the ones it cannot default. |
| `hipaa.env.example` | Every variable the overlay reads, with what each one is for. Copy it to `.env` beside the compose file and fill it in. |

```bash
docker compose -f docker-compose.yml -f deploy/profiles/hipaa/docker-compose.hipaa.yml up -d
```

There is no Helm values file yet: this repository ships no chart, and values for
a chart that does not exist would be a file nobody can apply. The settings below
transfer unchanged to whatever chart a deployment uses.

## The controls, and why each is where it is

| Control | Safeguard | Set by |
|---|---|---|
| `postgres-tls` | §164.312(e)(1) | `POSTGRES_SSLMODE=verify-full`. `require` encrypts and verifies no certificate, which is why the profile does not accept it |
| `redis-tls` | §164.312(e)(1) | `REDIS_SSL=true`. Redis carries queued work and cached answers |
| `vault-key` | §164.312(a)(2)(iv) | `VAULT_MASTER_KEY`. Every provider and connector credential is sealed per organization |
| `content-at-rest` | §164.312(a)(2)(iv) | **The operator's.** The application does not encrypt Postgres data, the media volume or the sandbox workspace root; a volume or a disk does. The sheet names it rather than passing it |
| `local-model` | §164.312(e)(1) | A model profile whose `base_url` is on your own network — Ollama, vLLM, a LiteLLM proxy. See below |
| `traces-local` | §164.312(e)(1) | `LOGFIRE_TOKEN` unset. A span with `observability.content: full` carries the message, the output and every tool argument |
| `sso` | §164.312(d) | `OIDC_ISSUER` and a client pair. Multi-factor authentication is the identity provider's job, and the profile says so rather than pretending to do it |
| `signup` | §164.312(a)(1) | `invite_only` or `closed`, set in the console under deployment settings |
| `audit-retention` | §164.312(b) | The audit floor, six years — §164.316(b)(2)'s number |
| `audit-chain` | §164.312(c)(1) | On by construction. Detection rather than prevention: anybody holding this database's own credentials can remove both the chain and its checkpoint |

## Why a local model, and not a vendor under an agreement

A hosted model takes the content of every run with it, so using one means a
business associate agreement with that vendor. Those agreements are narrower than
people expect: a HIPAA-enabled organization at a major vendor typically excludes
code execution and web fetch — which is the exact shape of the `sandbox`,
`code_execution` and `web_fetch` capabilities here. A client who signs one and
then builds an agent on those capabilities finds out during an incident.

Local inference removes the question. That is why it is the profile's default
rather than a suggestion, and why the doctor treats a model profile with no
`base_url` as reaching a third party: with no endpoint of its own, it is the
provider's public API by definition.
