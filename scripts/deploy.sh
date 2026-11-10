#!/usr/bin/env bash
#
# Deploy one commit onto a server that already runs this stack.
#
#   remote=$(ssh <host> 'mktemp -t agenticos-deploy.XXXXXX')
#   ssh <host> "cat > $remote" < scripts/deploy.sh
#   ssh <host> "trap 'rm -f $remote' EXIT; bash $remote <sha>"
#
# Copied to the server rather than run from its checkout: the checkout there is
# only where the compose files and `backend/.env` live, and the procedure
# travels with whoever is running it.
# Deliberately **not** taken from the commit being deployed - a rollback to a
# commit older than this file would then have no script to run, which is the one
# moment it is needed most.
#
# Copied and *then* run, rather than piped into `bash -s`, and that is not a
# style preference. Under `bash -s` the script is its own standard input, so the
# first command that reads stdin consumes the rest of it: `docker compose exec`
# forwards stdin to the container even with `-T`, so the migration swallowed
# everything below it, bash reached EOF, and the script exited 0 having never
# built the frontend or waited for anything (#1488).
#
# It takes a **commit**, not a branch. Two pushes can land while an approval is
# pending, and `git pull` on the server would then deploy whichever one won the
# race rather than the one somebody approved.
#
# Nothing is built here. `images.yml` publishes every commit on `main` as
# `ghcr.io/vstorm-co/agenticos-{backend,frontend}:sha-<short>`, and this pins
# `AGENTICOS_VERSION` to that tag and pulls - so what runs is byte-for-byte what
# CI built, and a host needs neither the toolchain nor the memory a build takes.
# The image is usually there before anybody has approved the deploy; when it is
# not yet, this waits for it rather than failing on the race.
#
# To roll back, run it again with the previous sha. There is nothing else to
# undo: the images are still in the registry, and a migration that has run stays
# run - which is why a rollback across one is a decision rather than a command.
#
# Not zero-downtime. Compose recreates the containers whose image changed, so the
# API and the site are unavailable for the few seconds that takes. Worth knowing
# before scheduling a deploy in the middle of somebody's conversation; not worth
# a blue environment for a deployment this size.
set -euo pipefail

release_repository() {
  case "$1" in
    ghcr.io/vstorm-co/agenticos-backend|ghcr.io/vstorm-co/agenticos-frontend|ghcr.io/vstorm-co/agenticos-browser) return 0 ;;
    *) return 1 ;;
  esac
}

image_in_list() {
  case $'\n'"$2"$'\n' in *$'\n'"$1"$'\n'*) return 0 ;; *) return 1 ;; esac
}

release_pin_prefix() {
  local scope
  scope=$(printf '%s' "$1" | git hash-object --stdin) || return
  [[ "$scope" =~ ^[0-9a-f]{40,64}$ ]] || return 1
  printf 'deploy-%s' "$scope"
}

container_image_ids() {
  local containers cid
  local ids=()
  containers=$(docker ps -aq) || return
  for cid in $containers; do ids+=("$cid"); done
  if [ "${#ids[@]}" -gt 0 ]; then
    docker inspect -f '{{.Image}}' "${ids[@]}" || return
  fi
}

# Every alias must belong to a release repository and be immutable. A local
# current/rollback pin, a runtime alias or another repository protects the ID.
# Status 1 means protected; a Docker error is a refusal, never an empty inventory.
removable_release_refs() {
  local id="$1" target="$2" refs digests ref repo tag
  refs=$(docker image inspect -f '{{range .RepoTags}}{{println .}}{{end}}' "$id") || return 2
  [ -n "$refs" ] || return 1
  for ref in $refs; do
    repo=${ref%:*}; tag=${ref##*:}
    release_repository "$repo" || return 1
    [[ "$tag" =~ ^(sha-[0-9a-f]{7,40}|v?[0-9]+\.[0-9]+\.[0-9]+)$ ]] || return 1
    [ "$tag" != "$target" ] || return 1
  done
  digests=$(docker image inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' "$id") || return 2
  for ref in $digests; do
    release_repository "${ref%@*}" || return 1
  done
  printf '%s\n' "$refs"
}

# Bootstrap from this stack's healthy containers, never the checkout. Once a
# successful release has been recorded, keep that pin across partial failures.
remember_release_images() {
  local app_dir="$1" prefix repo aliases current containers cid details id reference service health
  prefix=$(release_pin_prefix "$app_dir") || return
  containers=$(docker ps -q --filter "label=com.docker.compose.project.working_dir=$app_dir") || return
  for repo in ghcr.io/vstorm-co/agenticos-backend ghcr.io/vstorm-co/agenticos-frontend ghcr.io/vstorm-co/agenticos-browser; do
    aliases=$(docker image ls --format '{{.Repository}}:{{.Tag}}' "$repo") || return
    if image_in_list "$repo:$prefix-current" "$aliases"; then
      current=$(docker image inspect -f '{{.Id}}' "$repo:$prefix-current") || return
    else
      current=""
      for cid in $containers; do
        details=$(docker inspect -f '{{.Image}}|{{.Config.Image}}|{{index .Config.Labels "com.docker.compose.service"}}|{{with index .State "Health"}}{{.Status}}{{end}}' "$cid") || return
        IFS='|' read -r id reference service health <<< "$details"
        case "$service" in app|worker|frontend|browser|visual-render) ;; *) continue ;; esac
        [ "$health" = healthy ] || continue
        case "$reference" in "$repo":*|"$repo"@*) ;; *) continue ;; esac
        if [ -n "$current" ] && [ "$current" != "$id" ]; then
          echo "Cannot identify a healthy release for $repo: this stack runs multiple image IDs." >&2
          return 1
        fi
        current="$id"
      done
      if [ -n "$current" ]; then
        docker image tag "$current" "$repo:$prefix-current" || return
      fi
    fi
    [ -z "$current" ] || printf '%s|%s\n' "$repo" "$current"
  done
}

prune_release_images() {
  local target="$1" ids protected eligible="" retained="" id refs status created fraction repo ref newest
  local remove_refs=()
  ids=$(docker image ls --quiet --no-trunc | sort -u) || return
  protected=$(container_image_ids) || return
  for id in $ids; do
    image_in_list "$id" "$protected" && continue
    if refs=$(removable_release_refs "$id" "$target"); then
      created=$(docker image inspect -f '{{.Created}}' "$id") || return
      if ! [[ "$created" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z$ ]]; then
        echo "Cannot order release image $id: unsupported creation timestamp $created." >&2
        return 1
      fi
      # RFC3339Nano omits trailing zeroes. Pad fractions before sorting: .1Z
      # must precede .12Z, and a whole second must precede its fractions.
      created=${created%Z}
      if [[ "$created" = *.* ]]; then
        fraction="${created##*.}000000000"
        created="${created%%.*}.${fraction:0:9}Z"
      else
        created="$created.000000000Z"
      fi
      for repo in $(printf '%s\n' "$refs" | sed 's/:[^:]*$//' | sort -u); do
        eligible+="$created|$id|$repo"$'\n'
      done
    else
      status=$?
      [ "$status" -eq 1 ] || return "$status"
    fi
  done
  # Two additional unused image IDs per repository, not two aliases of one ID.
  # Union the keep sets: an image shared by repositories stays if either keeps it.
  for repo in ghcr.io/vstorm-co/agenticos-backend ghcr.io/vstorm-co/agenticos-frontend ghcr.io/vstorm-co/agenticos-browser; do
    newest=$(printf '%s' "$eligible" | LC_ALL=C sort -r | awk -F'|' -v repo="$repo" '$3 == repo && ++n <= 2 { print $2 }') || return
    retained+="$newest"$'\n'
  done
  for id in $(printf '%s' "$eligible" | awk -F'|' 'NF == 3 {print $2}' | sort -u); do
    image_in_list "$id" "$retained" && continue
    # Another client may have created a container or added an alias since the
    # inventory. Recheck both immediately before the non-forced removal.
    protected=$(container_image_ids) || return
    image_in_list "$id" "$protected" && continue
    if refs=$(removable_release_refs "$id" "$target"); then
      remove_refs=()
      for ref in $refs; do remove_refs+=("$ref"); done
      printf '  Removing unused release image %s: %s\n' "$id" "${remove_refs[*]}"
      docker image rm --no-prune "${remove_refs[@]}" || return
    else
      status=$?
      [ "$status" -eq 1 ] || return "$status"
    fi
  done
}

require_image_space() {
  local store="$1" available
  available=$(printf '%s\n' "$2" | awk 'NR == 2 {print $4}') || return
  if ! [[ "$available" =~ ^[0-9]+$ ]]; then
    echo "Cannot determine available space for Docker storage at $store." >&2
    return 1
  fi
  if [ "$available" -lt 5242880 ]; then
    echo "Insufficient space at $store: $available KiB available; at least 5242880 KiB (5 GiB) is required before pulling release images. Protected current/rollback, container and runtime images were retained. Free space outside those protections or expand this filesystem, then retry the approved deploy." >&2
    return 1
  fi
  echo "  $store: $available KiB available (minimum 5 GiB)"
}

check_image_space() {
  local root store system probe report
  root=$(docker info --format '{{.DockerRootDir}}') || return
  [ -n "$root" ] || { echo "Docker did not report its storage directory." >&2; return 1; }
  system=$(docker info --format '{{.OperatingSystem}}') || return
  case "$system" in
    *"Docker Desktop"*)
      # DockerRootDir is inside Desktop's VM. Query its backing filesystem using
      # an already-cached backend image; never pull an image to measure capacity.
      probe=$(printf '%s\n' "${1:-}" | awk -F'|' '$1 == "ghcr.io/vstorm-co/agenticos-backend" {image=$2} END {print image}') || return
      if [ -z "$probe" ]; then
        probe=$(docker image ls --quiet --no-trunc ghcr.io/vstorm-co/agenticos-backend | awk 'NR == 1 {first=$0} END {print first}') || return
      fi
      if ! [[ "$probe" =~ ^sha256:[0-9a-f]{64}$ ]]; then
        echo "Docker Desktop capacity check needs a cached AgenticOS backend image. Complete the initial installation before using this update procedure." >&2
        return 1
      fi
      report=$(docker run --rm --pull=never --read-only --network=none --cap-drop=ALL --entrypoint df "$probe" -Pk /) || return
      require_image_space "Docker Desktop VM" "$report" || return
      # The VM disk image also consumes host storage. A custom backing disk's
      # host filesystem still needs its own monitoring, like custom containerd.
      store="${APP_DIR:-$PWD}"
      report=$(df -Pk "$store") || return
      require_image_space "$store" "$report" || return
      return 0
      ;;
  esac
  # Engine 29's containerd store lives outside DockerRootDir by default.
  for store in "$root" /var/lib/containerd; do
    if [ "$store" != "$root" ] && [ ! -d "$store" ]; then continue; fi
    report=$(df -Pk "$store") || return
    require_image_space "$store" "$report" || return
  done
}

record_release_images() {
  local target="$1" previous="$2" prefix image repo id prior prior_repo prior_id
  prefix=$(release_pin_prefix "$3") || return
  shift 3
  for image in "$@"; do
    repo="ghcr.io/vstorm-co/$image"
    id=$(docker image inspect -f '{{.Id}}' "$repo:$target") || return
    prior=""
    while IFS='|' read -r prior_repo prior_id; do
      if [ "$prior_repo" = "$repo" ]; then prior="$prior_id"; fi
    done <<< "$previous"
    # A redeploy of the same image must not overwrite the previous rollback pin.
    if [ -n "$prior" ] && [ "$prior" != "$id" ]; then
      docker image tag "$prior" "$repo:$prefix-rollback" || return
    fi
    docker image tag "$id" "$repo:$prefix-current" || return
  done
}

SHA="${1:?usage: deploy.sh <commit-sha>}"
APP_DIR="${APP_DIR:-/opt/agenticos}"
COMPOSE_ENV="${APP_DIR}/backend/.env"
# The frontend is a project of its own, or compose - which names a project after
# the directory - reports the backend's containers as orphans of the frontend
# stack, and suggests the flag that would remove them. Matches the Makefile.
FRONTEND_PROJECT="agenticos-frontend"

say() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

cd "$APP_DIR"
test -f "$COMPOSE_ENV" || { echo "missing $COMPOSE_ENV" >&2; exit 1; }

# The effective value of a variable in the env file: the *last* assignment wins,
# the way dotenv and compose read it, and surrounding quotes are not part of the
# value. `grep -q` on the name answers a different question - whether the file
# mentions it - so `NAME=""`, or a real value later disabled by a bare `NAME=`,
# both read as set (#1506).
env_value() {
  sed -n "s/^$1=//p" "$COMPOSE_ENV" | tail -1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

# Which reverse proxy this host was set up with, read from the host rather than
# assumed. Hard-coding the Traefik overlays meant an Nginx host was silently
# converted on its next deploy - and since the overlay declares
# `traefik_webgateway` external, on a host that never created it compose fails
# outright, which is the better of the two outcomes.
PROXY="$(env_value PROXY)"
case "${PROXY:-nginx}" in
  traefik)
    BACKEND=(-f docker-compose-prod.yml -f docker-compose-prod.traefik.yml)
    FRONTEND=(-p "$FRONTEND_PROJECT" -f docker-compose-prod.frontend.yml -f docker-compose-prod.frontend.traefik.yml)
    ;;
  nginx|"")
    BACKEND=(-f docker-compose-prod.yml)
    FRONTEND=(-p "$FRONTEND_PROJECT" -f docker-compose-prod.frontend.yml)
    ;;
  *)
    echo "PROXY=$PROXY in $COMPOSE_ENV is not one of: traefik, nginx" >&2
    exit 1
    ;;
esac

# The sandbox service is behind a compose profile, so it is opt-in - and a
# profile compose is not told about is a service compose treats as nothing to do
# with this project. It does not merely leave it alone: `up -d` on the same
# project without the profile stops it. So a host that started the sandbox by
# hand had it taken away by its next deploy, silently, and an agent's code
# execution stopped working for reasons nowhere near the deploy that
# caused it (#1506).
#
# Read from the host, the same way `PROXY` is: `SANDBOXD_TOKEN` is what the
# service refuses to start without, so a non-empty one in `backend/.env` is this
# host saying it runs a sandbox.
PROFILES=()
VISUAL_RENDERER=false
INTERACTIVE_BROWSER=false
if [ -n "$(env_value SANDBOXD_TOKEN)" ]; then
  PROFILES=(--profile sandbox)
  if [ ! -S /var/run/docker.sock ]; then
    echo "no /var/run/docker.sock, but SANDBOXD_TOKEN is set - the sandbox cannot start" >&2
    exit 1
  fi
  # Docker Desktop's mounted socket belongs to VM group 0, not the Mac's group.
  if [ -z "${DOCKER_GID+x}" ]; then
    if [ "$(uname -s)" = Linux ]; then
      DOCKER_GID="$(stat -Lc '%g' /var/run/docker.sock)"
    else
      DOCKER_GID=0
    fi
  fi
  export DOCKER_GID
fi

# Keep the isolated visual renderer running across deploys, like the sandbox.
case "$(env_value VISUAL_RENDER_CDP_URL)" in
  http://visual-render:9222|http://visual-render:9222/)
    PROFILES+=(--profile visuals)
    VISUAL_RENDERER=true
    ;;
esac

case "$(env_value BROWSER_SIGN_IN_CDP_URL)" in
  http://browser:9222|http://browser:9222/)
    PROFILES+=(--profile browser)
    INTERACTIVE_BROWSER=true
    ;;
esac

say "Remembering the last healthy release images"
PREVIOUS_RELEASE_IMAGES=$(remember_release_images "$APP_DIR")

say "Fetching $SHA"
git fetch --prune --quiet origin
git checkout --quiet --detach "$SHA"
git --no-pager log --oneline -1

# The tag `images.yml` gave this commit. Exported rather than written to the env
# file, so the file keeps saying what the operator wrote and the pin lives
# exactly as long as this deploy; the compose files default to `latest` when it
# is absent, which a `docker compose up` by hand on this host would then get.
# `cut`, not `--short=7`: git widens a short sha past seven characters when it
# is ambiguous, and metadata-action never does.
AGENTICOS_VERSION="sha-$(git rev-parse HEAD | cut -c1-7)"
export AGENTICOS_VERSION

# `images.yml` starts when the commit lands on `main`, the same moment this
# workflow does, and finishes some minutes later - so an approval given at once
# would pull a tag that does not exist yet. Wait for the manifest rather than
# fail on it; twenty minutes is a stalled publish, not a slow one.
#
# A commit that never had a run - older than `images.yml`, or its run lost -
# is not a wait, and the message says what publishes it: the same workflow,
# dispatched with the commit, which gives it its `sha-` tag and nothing that
# moves.
say "Waiting for the images tagged $AGENTICOS_VERSION"
IMAGES=(agenticos-backend agenticos-frontend)
if "$VISUAL_RENDERER" || "$INTERACTIVE_BROWSER"; then
  IMAGES+=(agenticos-browser)
fi
for image in "${IMAGES[@]}"; do
  ref="ghcr.io/vstorm-co/$image:$AGENTICOS_VERSION"
  for attempt in $(seq 1 80); do
    if docker manifest inspect "$ref" >/dev/null 2>&1; then
      echo "  $ref"
      break
    fi
    if [ "$attempt" -eq 80 ]; then
      {
        echo "  $ref is not in the registry after 20 minutes."
        echo "  If the Images workflow never ran for $SHA - a commit older than it, or a run that was lost -"
        echo "  publish it first, then deploy again:"
        echo "    gh workflow run images.yml --repo vstorm-co/agenticos --ref main -f sha=$SHA"
      } >&2
      exit 1
    fi
    sleep 15
  done
done

# `< /dev/null` on every compose call, so this stays correct even when somebody
# pipes the script into `bash -s` anyway: nothing in here has any business
# reading standard input, and one that does silently truncates the deploy (#1488).
compose() { docker compose --env-file "$COMPOSE_ENV" "$@" < /dev/null; }

# `up -d`, with one retry when it gives up on a dependency's health.
#
# `depends_on: condition: service_healthy` reads the dependency's health status
# the instant the container starts, and a daemon that carried the previous run's
# `unhealthy` across the restart answers with it - before this run's first probe
# has had a chance to replace it. So the deploy fails half a second after
# starting the very container that fixes the problem, with the message the real
# failure printed a moment earlier, and the next attempt passes untouched
# (#1831). The `start_period` on those healthchecks is the half of this the
# compose files can state; this is the half the daemon decides.
#
# One retry, and only for this failure: anything else is a broken deploy and
# should stop here rather than be attempted twice.
compose_up() {
  local output
  if output=$(compose "$@" up -d 2>&1); then
    printf '%s\n' "$output"
    return 0
  fi
  printf '%s\n' "$output" >&2
  case "$output" in
    *"is unhealthy"*)
      say "A dependency answered with the health status it had before this start - waiting for its first probe"
      sleep 15
      compose "$@" up -d
      ;;
    *)
      return 1
      ;;
  esac
}

# The API first, and its migrations before the frontend: a frontend serving a
# schema the backend has not migrated to yet is the window this ordering closes.
# The migrations are the `migrate` service, which `app` waits on, so `up -d` is
# the whole of it; `docker compose logs migrate` has the story when the API
# never comes up.
# Before the new sandboxd replaces the old one. sandboxd builds a runtime's image
# lazily, so a release that changed a runtime left the first sandboxed chat
# waiting minutes on a build on this host, every session request answering 409
# (#2222). A one-off container of the new image builds them now, while the old
# service keeps serving, and the new one starts with every image in the cache.
# Not fatal: a runtime this cannot prepare is still built when a session asks.
# Takes the compose file and profile arguments; does nothing without the sandbox
# profile, since there is then no sandboxd to prepare for.
prepare_sandbox_runtimes() {
  case " $* " in *" --profile sandbox "*) ;; *) return 0 ;; esac
  say "Preparing the sandbox runtimes"
  if ! compose "$@" run --rm --no-deps -T sandboxd python -m pydantic_ai_backends.remote.prepare; then
    echo "  Not every sandbox runtime is prepared; sandboxd builds the rest when a session asks." >&2
  fi
}

# Services a release removed from the compose file. Compose leaves a container
# whose service left the file running as an "orphan", and for Prefect that is a
# scheduler still dispatching the old periodic work beside the worker that
# replaced it (#2219). Removed by name rather than with `--remove-orphans`, which
# would take anything else a host still runs under this project with it, and
# before the API starts, so the old scheduler and the new worker never overlap.
# Matched on the project's working directory, the label every compose container
# carries, so another stack on the host keeps its own.
RETIRED_SERVICES=(prefect-server prefect-runner)
retire_services() {
  local service ids
  for service in "${RETIRED_SERVICES[@]}"; do
    ids=$(docker ps -aq \
      --filter "label=com.docker.compose.project.working_dir=$APP_DIR" \
      --filter "label=com.docker.compose.service=$service")
    if [ -n "$ids" ]; then
      say "Removing the retired $service"
      # Unquoted: one id per word, and there may be several.
      docker rm -f $ids >/dev/null
    fi
  done
}

say "Reclaiming unused release images before pulling"
prune_release_images "$AGENTICOS_VERSION"
check_image_space "$PREVIOUS_RELEASE_IMAGES"

say "Pulling the API images"
compose "${BACKEND[@]}" "${PROFILES[@]+"${PROFILES[@]}"}" pull --quiet
check_image_space "$PREVIOUS_RELEASE_IMAGES"
say "Pulling the frontend image"
compose "${FRONTEND[@]}" pull --quiet

prepare_sandbox_runtimes "${BACKEND[@]}" "${PROFILES[@]+"${PROFILES[@]}"}"
check_image_space "$PREVIOUS_RELEASE_IMAGES"
retire_services
say "Starting the API"
compose_up "${BACKEND[@]}" "${PROFILES[@]+"${PROFILES[@]}"}"

say "Starting the frontend"
compose_up "${FRONTEND[@]}"

# A deploy that finished is not a deploy that works. Compose returns as soon as
# the containers are started, so without this a broken image is discovered by
# whoever opens the site next.
# By service, through compose, not by a fixed container name: the compose files
# carry none, so each project names its own containers and two stacks on one
# host stop taking each other's over.
#
# `unhealthy` is a verdict on this run only once a probe has run since the
# container started. Before that it is the status the previous run left behind,
# which `compose_up` above has the whole story on: acting on it here would fail
# the deploy for the same reason compose did, one step later and with the
# container's old logs as the evidence.
wait_healthy() {
  local service="$1"; shift
  local cid attempt status started probed
  for attempt in $(seq 1 60); do
    # Re-read every round, and with `-a`: between restart attempts the container
    # is stopped and `ps -q` alone lists nothing, which would pin an empty id
    # for the whole wait.
    cid=$(compose "$@" ps -a -q "$service")
    status=$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo missing)
    case "$status" in
      healthy) echo "  $service: healthy"; return 0 ;;
      unhealthy)
        # `.End.Unix` is an integer out of the template; `StartedAt` is a string,
        # so it goes through `date`. A container with no probe yet has neither,
        # and waits.
        started=$(date -d "$(docker inspect -f '{{.State.StartedAt}}' "$cid")" +%s 2>/dev/null || echo 0)
        probed=$(docker inspect -f '{{range .State.Health.Log}}{{.End.Unix}} {{end}}' "$cid" 2>/dev/null | awk '{print $NF}')
        if [ -n "$probed" ] && [ "$probed" -gt "$started" ]; then
          echo "  $service: unhealthy" >&2
          compose "$@" logs --tail 50 "$service" >&2
          exit 1
        fi
        ;;
    esac
    if [ "$attempt" -eq 60 ]; then
      echo "  $service: still $status after 120s" >&2
      compose "$@" logs --tail 50 "$service" >&2
      exit 1
    fi
    sleep 2
  done
}

say "Waiting for health"
wait_healthy app "${BACKEND[@]}" "${PROFILES[@]+"${PROFILES[@]}"}"
wait_healthy frontend "${FRONTEND[@]}"
if "$VISUAL_RENDERER"; then
  wait_healthy visual-render "${BACKEND[@]}" "${PROFILES[@]}"
fi

if "$INTERACTIVE_BROWSER"; then
  wait_healthy browser-egress "${BACKEND[@]}" "${PROFILES[@]}"
  wait_healthy browser "${BACKEND[@]}" "${PROFILES[@]}"
fi

say "Recording the healthy release and its rollback images"
record_release_images "$AGENTICOS_VERSION" "$PREVIOUS_RELEASE_IMAGES" "$APP_DIR" "${IMAGES[@]}"
df -h / | tail -1

say "Deployed $(git rev-parse --short HEAD)"
