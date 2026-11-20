# Docker image retention

`retain_images.py` is an opt-in, host-local operator helper for a Compose
deployment. It reports a plan by default. `--apply` removes only old, unused
images from explicitly named repositories after validating the daemon, release
pins, deployed containers and a shared deployment lock.

This directory does **not** install a timer, modify a Docker daemon, enable CI,
or change Coolify settings. Review the deployment and existing cleanup jobs
before enabling deletion. Run it with Python 3.11 or newer on the Docker host.
It uses the standard library and the installed Docker CLI.

## Retention contract

The helper protects:

- Every image referenced by **any running or stopped container on the host**.
- The exact current image and previous successful image for every configured
  Compose service, including a worker sharing an API image.
- Every tag and digest alias of a protected image ID.

The previous successful release must come from recorded deployment and health
results. The two newest images are not necessarily two working releases. A tag
named `rollback` does not itself protect an image from other cleanup tools.

An image is eligible only when it belongs to the exact repository allowlist,
has no container references, is not pinned, and is at least seven days old by
default. The helper checks all `RepoTags` and `RepoDigests`; it skips dangling
images, mixed ownership, multiple repository aliases, and multiple tags rather
than partially untagging an uncertain image. At most ten images are selected per
run by default. Image sizes in reports are not a promise of reclaimed space:
layers can be shared.

Before each removal the helper rereads the daemon, image and container inventory.
Unexpected changes stop the run. Removal uses the full Docker image ID with
`docker image rm --no-prune`, without force, and confirms that the image is gone.
No container, volume, network, build-cache or system pruning is performed.

## Configure a private policy

Start from [policy.example.json](policy.example.json). All identifiers and
registry names in that file are synthetic. Store the actual policy outside the
repository, for example at `/etc/t3os/image-retention.json`, and keep it owned by
root or the effective user with mode `0600` or `0400`. Symlink policies and
duplicate or unknown fields are refused.

Inventory the target host without printing container environments or secrets:

```sh
docker info --format '{{.ID}} {{.DockerRootDir}}'
docker ps -a --format '{{.ID}} {{.Image}} {{.Names}}'
docker inspect --format '{{.Image}} {{index .Config.Labels "com.docker.compose.project"}} {{index .Config.Labels "com.docker.compose.service"}} {{.State.Status}}' CONTAINER_ID
docker image inspect --format '{{.Id}} {{json .RepoTags}} {{json .RepoDigests}}' IMAGE_REFERENCE
```

Copy the exact daemon ID, project label, service labels and repository names.
Release pins are full `sha256:…` **Docker image/config IDs returned by image
inspect**. Do not assume a registry manifest or manifest-list digest is the same
ID. Resolve the pulled image locally before recording its pin.

For each component, the current pin must match a running, healthy container with
the configured Compose project and service labels. The previous successful pin
must exist locally and carry an alias in the configured repository. Every
allowlisted repository must be represented by a component. Do not insert a
guessed previous release just to pass validation.

| Policy field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `docker_host` | Explicit local `unix:///` Docker socket; remote hosts are refused |
| `daemon_id` | Exact `docker info` daemon ID |
| `compose_project` | Exact Compose project label |
| `lock_file` | Absolute local lock path shared by deployment and cleanup |
| `repositories` | Exact image repositories; no tags or patterns |
| `components` | Service names mapped to repository, current pin and previous successful pin |
| `minimum_age_days` | Minimum image age; default `7` |
| `max_removals` | Maximum selected removals in one run; default `10` |
| `min_free_gib` | Required free space for `--check-space`; default `20` GiB |
| `min_free_percent` | Required free percentage for `--check-space`; default `20` |

Create the lock directory with private permissions, and install the reviewed
script without altering its contents:

```sh
sudo install -d -m 0700 /etc/t3os /var/lib/t3os-image-retention
sudo install -m 0755 integrations/docker-image-retention/retain_images.py /usr/local/sbin/t3os-retain-images
# Install a completed, reviewed private policy as /etc/t3os/image-retention.json.
# Do not install policy.example.json unchanged on a live host.
```

## Inspect, check capacity, then apply

```sh
sudo /usr/local/sbin/t3os-retain-images --policy /etc/t3os/image-retention.json
sudo /usr/local/sbin/t3os-retain-images --policy /etc/t3os/image-retention.json --check-space
sudo /usr/local/sbin/t3os-retain-images --policy /etc/t3os/image-retention.json --apply --writers-coordinated
```

The first command reports a dry run. Review the exact selected IDs and aliases.
The space check examines the local filesystem containing Docker's root directory
and requires **both** free-space floors. It is intended to stop a build or pull
before it consumes the remaining disk; it is not a reservation or a guarantee
that an arbitrarily large build will fit. Budget additional space for the
specific build and for other services sharing the filesystem.

| Exit code | Meaning |
| --- | --- |
| `0` | Completed dry run or apply, or space check passed |
| `2` | Configuration, identity, inventory, Docker, lock or other safety check failed |
| `3` | `--check-space` found less free space than either configured floor |

Operation reports are JSON; invalid CLI arguments use argparse's error output.
An apply failure lists confirmed removals and, if applicable,
the image whose removal was attempted but could not be confirmed. Reinspect
that image before retrying; a failed command is not evidence that nothing
changed. A dry run reports low space without changing its purpose into an
automatic cleanup request.

## Coordinate deployment and other cleanup

`--apply` requires `--writers-coordinated`, an explicit operator acknowledgment
that every image writer and cleanup process either shares the lock or will stay
quiesced for the entire maintenance window. The acknowledgment is refused with
dry-run or space-check modes and does not itself verify coordination.

`--apply` takes a nonblocking exclusive `flock` on `lock_file`. Every cooperating
build, pull, deployment, release-pin update and cleanup must hold that same lock.
The helper cannot prove that another deployment mechanism honors the lock.
Docker has no atomic inspect-and-delete transaction; reinspection and non-forced
removal reduce risk but do not replace coordination.

A deployment wrapper should hold the lock from its capacity check through
pull/build, rollout, health verification and atomic policy replacement. Promote
the former healthy current ID to `previous_successful_image_id` only after the
new release passes its health checks. Keep the prior pins if rollout fails.
`--check-space` does not acquire the apply lock, so it can run inside that wrapper.
Run `--apply` after the wrapper releases the lock, or as a separate coordinated
maintenance step.

**Coolify UI deployments do not automatically acquire this helper's lock.** Do
not add an unattended destructive timer until all relevant deployment and image
mutation paths are coordinated. During an explicitly coordinated maintenance
window, inspect the dry run again immediately before applying. No image-cleanup timer is
included here because its safety depends on deployment integration.

## Interaction with Coolify cleanup

Inspect **Server → Docker Cleanup**, its recent execution output, and other
host timers before changing anything. Coolify supports a schedule and disk
threshold; manual cleanup bypasses those triggers. Keep volume and network
deletion disabled unless their data and ownership have been reviewed separately.

In Coolify **v4.6.0**, application image retention is based on Application
records. A Compose **Service** is a separate resource type, so “Keep retained
images” does not by itself preserve that Service's previous release. The generic
image cleanup checks the **image's** `coolify.managed=true` label; the same label
on a container is not equivalent. A release-pins policy protects against this
helper only and does not constrain Coolify, cron jobs or manual Docker commands.

Resolve that interaction before promising local rollback retention. Options
include a deliberately integrated image-retention mechanism or verified
immutable release images in a registry with a tested restore procedure. Registry
availability is a restore option, not proof that a local rollback image survives.
Do not change unrelated server-wide cleanup settings merely to install this
helper.

## Build-cache growth

Build cache is separate from image retention. Measure it with `docker system df`
and inspect the relevant builder before changing its cache policy. This helper
does not run `docker builder prune -af`, `docker buildx prune -af`, or any
server-wide prune command.

For repeated demo builds, prefer a dedicated builder with a bounded cache policy
and the same deployment lock, or publish images from a build service and only
pull them on the runtime VM. Choose the cache limit from observed build size and
available headroom; a 5–10 GiB budget may be a starting point, not a universal
safe value. Inspect shared builders and active builds before any pruning.

### Optional daily cache cleanup

The included [service](docker-unused-build-cache.service) and
[timer](docker-unused-build-cache.timer) remove default-builder cache that has
not been used for 24 hours. They run independently of disk usage and retain no
arbitrary cache-size budget. Docker only prunes eligible unused cache; records
actively used by BuildKit are not reclaimable. Later builds may need to rebuild
more layers.

This is **cache-only** maintenance. It does not run the image-retention helper,
remove images or containers, prune volumes or networks, or restart Docker.
It affects the shared default builder, so review that scope before installation.
The service skips an inactive Docker daemon. The schedule is daily at 00:30 UTC
with up to five minutes of jitter and catch-up after downtime.

On a systemd host where Docker and systemctl are installed under /usr/bin:

```sh
sudo install -m 0644 integrations/docker-image-retention/docker-unused-build-cache.service /etc/systemd/system/
sudo install -m 0644 integrations/docker-image-retention/docker-unused-build-cache.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/docker-unused-build-cache.service /etc/systemd/system/docker-unused-build-cache.timer
sudo systemctl daemon-reload
sudo systemctl enable --now docker-unused-build-cache.timer
sudo systemctl list-timers docker-unused-build-cache.timer
```

Inspect results with `journalctl -u docker-unused-build-cache.service`.
Disable future runs with `systemctl disable --now docker-unused-build-cache.timer`.
A timer is installed only when an operator runs these commands. The image
cleanup coordination requirements above are unchanged.

## Verification

Run the focused, deterministic suite without a Docker daemon:

```sh
python3 -m unittest discover -s integrations/docker-image-retention/tests -v
python3 integrations/docker-image-retention/retain_images.py --help
```

The tests use synthetic Docker responses and temporary local locks. They cover
release and container protection, aliases, age and removal bounds, refusal on
drift, failed/uncertain removals, policy validation and capacity checks. They do
not establish that a real deployment shares the lock or that a rollback release
has passed health checks. Record those live acceptance checks per deployment.

## References

- [Coolify automated Docker cleanup](https://coolify.io/docs/core/infrastructure/servers/automated-docker-cleanup)
- [Coolify v4.6.0 cleanup implementation](https://github.com/coollabsio/coolify/blob/v4.6.0/app/Actions/Server/CleanupDocker.php)
- [Docker image removal](https://docs.docker.com/reference/cli/docker/image/rm/)
- [Docker image prune](https://docs.docker.com/reference/cli/docker/image/prune/)
- [Docker build-cache garbage collection](https://docs.docker.com/build/cache/garbage-collection/)
