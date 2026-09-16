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
| `docker-compose.hipaa.yml` | An overlay over the repository's `docker-compose.yml`. It sets `ENVIRONMENT=production` and the transport and observability settings the profile asks for, and refuses to start without the ones it cannot default. |
| `hipaa.env.example` | Every variable the overlay reads, with what each one is for. Copy it to `.env` beside the compose file and fill it in. |

**Bring your own Postgres and Redis.** The repository's bundled `db` and `redis`
services are for development: they have no TLS listener and no certificate, so
`verify-full` cannot connect to either. The overlay therefore requires
`POSTGRES_HOST` and `REDIS_HOST` and will not start without them, rather than
coming up on a plaintext socket while the sheet reports TLS. It requires a
`SECRET_KEY` of your own for the same reason - the repository ships a
development one, and it signs every session token.

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
| `vault-key` | §164.312(a)(2)(iv) | `VAULT_MASTER_KEY`, at least 64 characters. HKDF derives a correctly sized wrapping key from anything and cannot add entropy to a guessable secret, so a short one is refused |
| `content-at-rest` | §164.312(a)(2)(iv) | **The operator's.** The application does not encrypt Postgres data, the media volume or the sandbox workspace root; a volume or a disk does. The sheet names it rather than passing it |
| `local-model` | §164.312(e)(1) | Every model profile's `base_url` on your own network — Ollama, vLLM, a LiteLLM proxy. The **hostname** is parsed and matched, not the URL searched, so `https://ollama.vendor.example` does not count as local. See below |
| `traces-local` | §164.312(e)(1) | `LOGFIRE_TOKEN` unset, **and** no published agent or named environment carrying a tracing token of its own — each attaches an exporter, and `observability.content` defaults to `full` |
| `browser-tls` | §164.312(e)(1) | `FRONTEND_URL` and `PUBLIC_BASE_URL` on https. Terminating it is your reverse proxy's, and is attested; an http address here is refused, because every other control can pass while a sign-in crosses the client boundary in plaintext |
| `sso` | §164.312(d) | `OIDC_ISSUER` and a client pair. **Not available yet** - generic OIDC sign-in is [#1419](https://github.com/vstorm-co/agenticos/issues/1419), so this control reports unmet on any deployment today, which is the truth about one where people still sign in with passwords. Multi-factor authentication is the identity provider's job, and the profile says so rather than pretending to do it |
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
