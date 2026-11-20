---
name: deploying-agenticos
description: Installs, verifies and updates a local or single-server AgenticOS deployment using the repository's existing scripts. Use for Docker setup, bootstrap, deployment checks, upgrades, backups or recovery; this work needs a terminal or authorized host access, not only platform MCP.
---

# Install and verify AgenticOS

Determine the target before executing: a local isolated installation, a named
server or an existing deployment. An organization MCP connection is not host
administration authority. Use the user's authorized terminal/SSH or CI executor.
Read `docs/deploy.md` and `docs/configuration.md` in the selected checkout.

## Isolated local verification

From the checkout, `scripts/agenticos_smoke.py` prepares a dedicated Compose
project, published images and a deterministic local model. Its default prints
the plan. `--run` starts the isolated stack, bootstraps an owner, checks the
console, connects a real MCP client and runs an agent. It uses no paid provider.
The fixture proves the platform plumbing; it does not measure model quality.
Report the pinned image version and any unverified path. Do not call this TLS,
external DNS or production-provider validation.

## Single host

1. Read the host's existing setup; choose the release, two public hostnames and
   reverse proxy. Check capacity, engine/Compose, DNS and ports before changes.
2. Use upstream published images unless the user requested a modified fork.
3. Run `scripts/server-init.sh` once on a fresh host. It refuses to overwrite an
   existing env file. Keep its generated secrets on the host; never print `.env`.
4. Start the documented Compose/proxy combination and wait for migrations and
   service health. Pin the release checkout and `AGENTICOS_VERSION` together.
5. Use `agenticos cmd bootstrap` in the API container to initialize the intended
   organization and owner. A provider key is entered through secure setup or an
   operator-controlled environment; never ask the user to paste it into chat.
6. Test API readiness and the console from outside the host. Complete sign-in,
   SMTP and a real provider-backed chat test when configured.
7. Connect the client's `/mcp`, run `whoami`, and verify a small authorized
   resource flow. Continue with operating or solution-building instructions.

A healthy container does not prove the public network, WebSocket, mail or model
provider works. Name each unchecked dependency explicitly.

## Update and recovery

Read the current SHA, image digests, migration state and upgrade instructions.
Back up database, media and the vault master key together, off the host, using
the documented procedure. Confirm recovery requirements before a schema change.
Use `scripts/deploy.sh <commit-sha>` or the guarded deployment workflow; do not
replace the target with a moving branch during approval.

Inspect health and an actual run afterwards. Code rollback retains migrations;
check compatibility before deploying old code. Data restore is a separate,
explicitly authorized operation. Do not turn a failed health check into an
unattended downgrade or database restore. Use `agenticos cmd doctor` for
application readiness and the host's own tools for CPU, disk and containers.
