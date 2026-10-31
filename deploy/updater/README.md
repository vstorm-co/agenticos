# Local Compose updates

The optional updater lets a deployment administrator prepare, schedule and apply
published AgenticOS releases from **Administration → Deployment**. It runs on the
Docker host, outside the application checkout. Recreating the API container does
not interrupt it. Nothing installs or updates automatically when this code lands.

## Supported deployments

Use a single Linux host with systemd, Python 3.12 or later at `/usr/bin/python3`,
Docker Engine 24+ and Compose 2.24+. The host must have Git, access to GitHub/GHCR,
a clean AgenticOS production checkout, a running `app`, `worker` and `db`, and
local media storage. Configure a working production backend and frontend first.
The checkout's owner must be able to write its Git metadata. Keep the updater's
program and configuration root-owned: the API must not be able to modify them.

The helper preserves the repository's nginx/Traefik overlays and configured
sandbox, browser and visual-render profiles. It refuses remote workers, external
file storage, removed services and changes to infrastructure image versions.
Custom Compose overlays, multiple API hosts, external databases and custom
storage require your deployment pipeline instead. Set `UPDATE_PIPELINE_URL` to
an HTTPS pipeline page to expose a link; the API does not trigger that pipeline.

## One-time operator setup

Review this code and your backup/recovery procedure first. From the production
checkout, explicitly install the service (replace the path and project name):

```bash
sudo /usr/bin/python3 deploy/updater/install.py \
  --app-dir /srv/agenticos --backend-project agenticos --api-gid 1000
```

This copies the helper to `/opt/agenticos-updater`, installs its systemd unit and
starts the helper. It does **not** restart or update AgenticOS. The default GID
matches the production API image; use the actual container group if customized.
On the next intentional backend restart, include `docker-compose-prod.updater.yml`
and set `UPDATE_STATE_DIR=/run/agenticos-updater`. Keep your existing proxy
overlays, profiles, project name and environment file. For the default nginx setup:

```bash
UPDATE_STATE_DIR=/run/agenticos-updater docker compose \
  --env-file backend/.env -p agenticos \
  -f docker-compose-prod.yml -f docker-compose-prod.updater.yml up -d
```

The overlay mounts only the updater runtime directory **read-only** into API and
worker containers and configures `UPDATE_AGENT_SOCKET`. It never mounts the Docker
socket into the API. The root helper accepts requests only through a local Unix
socket (group access, no TCP listener). App-admin API endpoints accept a validated
version, operation ID and schedule, not commands, image URLs or filesystem paths.
Treat app-admin access and access to that socket as deployment authority.

## What the buttons do

1. **Prepare update** verifies a stable published GitHub release, checks that its
   tag belongs to upstream main and is newer than the checked-out version,
   validates Compose configuration and storage, checks free space, pulls images,
   pins their digests and takes a preliminary backup. It does not deploy.
2. **Update now** or **Schedule** starts the same operation. Scheduling supports
   the next seven days and survives helper restarts. Ready/scheduled operations
   can be cancelled; an executing migration cannot.
3. Admission closes for HTTP work, new agent runs and worker job claims. Existing
   runs, claimed jobs and voice calls get up to 15 minutes to finish. No active
   work is force-killed to satisfy that deadline.
4. API and worker stop before the final backup. The helper switches to the
   prepared commit, persists `AGENTICOS_VERSION`, runs migrations explicitly,
   starts the pinned images and checks container health and API dependency
   readiness. Only then does admission reopen.

Preparation time and downtime depend on image downloads, active work, database
size and migrations. The panel gives a qualitative estimate, not a guaranteed
maintenance duration. During API recreation the panel may temporarily reconnect;
progress remains on the host and is available again when the API returns.

## Backups and recovery

`/var/lib/agenticos-updater/backups/<operation-id>/{prepared,final}` contains the
PostgreSQL custom-format dump, local media, private environment copy and restore
metadata. The final backup is taken with application writers stopped. Backups do
not include external storage, external sandbox contents or an independent copy
of the Docker host. Keep your existing off-host backup policy.

State and private audit records remain in `/var/lib/agenticos-updater`; runtime
control and socket are in `/run/agenticos-updater`. Operation state restores
maintenance after a host restart. Missing/unreadable control state on a configured
API refuses new work while admin, authentication and health paths remain usable.
The audit records the authenticated administrator ID and closed action parameters;
it does not record configuration contents or command output.

Before migration starts, a failed final backup attempts to restart the existing
API/worker and reopen admission. Once checkout/migration starts, any failure
leaves admission closed. A helper restart during execution also marks the
operation interrupted; it never guesses that a partially applied migration is
safe to repeat. An operator must inspect `journalctl -u agenticos-updater`, the
operation and backups, recover the database/media and previous images if needed,
and verify readiness. There is no automatic database downgrade or destructive
restore button. Clear maintenance only after that verification, by atomically
setting `requires_recovery` to false in the root-owned operation state and
restarting the helper. Never clear it merely to dismiss an error in the UI.

Backups and prepared worktrees are retained until the operator removes them.
Monitor disk usage and remove only completed operations no longer needed for
recovery, including their Git worktree registrations. The helper reserves space
for preparation/final backups plus 4 GiB, but this is an estimate, not a storage
quota or backup retention policy.

## Verification scope

Scoped tests exercise the actual state machine against Docker/Git boundary
doubles, including migration failure, backup failure, scheduling and interrupted
recovery. They do not execute a production update. Validate the complete flow on
a disposable deployment with your own restore procedure before enabling it on a
production host.
