---
name: developing-agenticos
description: Prepares an AgenticOS fork for platform changes, its own published images and upstream updates. Use when the user wants to fork AgenticOS, customize the platform or deploy their own modified distribution.
---

# Develop and deploy the intended repository

Read the checkout's `AGENTS.md` and manifests. Separate changing platform code
from configuring an agent: the latter belongs in a versioned agent spec.

## Choose the source

1. Inspect git remotes and the branch. Use GitHub tools or `gh` to inspect an
   existing fork; create one only within the user's requested scope.
2. Keep `origin` as the user's fork and `upstream` as `vstorm-co/agenticos`.
3. Fetch upstream and branch new work from fresh `upstream/main`. Preserve local
   edits and commits; do not reset the fork or force-push to synchronize it.
4. Follow the repository's scoped tests and lint checks. Submit platform changes
   through a PR; do not silently modify the upstream installation.

## Images and deployment

The Images workflow publishes to `ghcr.io/<owner>/<repository>` by default,
lowercased. `AGENTICOS_IMAGE_PREFIX` is an optional GitHub repository variable
that selects another GHCR repository prefix. Package publishing uses that
repository's `GITHUB_TOKEN`, whose package permissions must cover the destination.
The workflow publishes only commits on that repository's `main`.

On the host set, for example:

```dotenv
AGENTICOS_IMAGE_PREFIX=ghcr.io/example/agenticos
AGENTICOS_SOURCE_REPOSITORY=example/agenticos
```

Compose and `scripts/deploy.sh` use that prefix for backend, frontend and browser
images. The separately versioned sandbox daemon remains its upstream dependency.
A fork intended only to track upstream can keep upstream application images.

Check the image digests and deployed SHA. An upstream image is not proof that a
fork's code runs. Configure the deployment workflow's SSH secrets through the
person's secure GitHub settings, and verify the `production` environment's
required reviewers before enabling automatic release deployments. Forking does
not copy every repository setting, secret or protection.

## Update from upstream

Fetch `upstream`, review the commits and upgrade notes, and prepare an update
branch/PR. Preserve fork customizations and resolve conflicts explicitly. After
CI passes and the update is merged, publish images from that exact fork commit,
then deploy its SHA through the existing deployment procedure. Never use a pull
from a diverged fork main as evidence that an upstream change landed.
