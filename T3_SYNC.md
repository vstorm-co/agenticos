# T3OS downstream updates

This repository contains a deterministic downstream updater and CI definitions.
Installing these files does not enable a trigger, grant access or establish a
passing CI check. The initial rollout still requires the cloud and GitHub setup
below. GitHub Actions runs checks only in this fork; central validation and
downstream updates use Cloud Build.

## Execution and trust

1. A pull request to `t3` runs `t3os-platform-pr`. A push to `t3` runs the distinct
   `t3os-platform-validated` trigger against the exact pushed commit.
2. The push validator publishes build notifications to the dedicated
   `t3os-platform-validations` topic. The updater filters for `SUCCESS`. PR builds
   and the updater itself use the default `cloud-builds` topic, avoiding a loop.
3. The updater receives only the build ID. It retrieves that build through the
   Cloud Build API and verifies its project, trigger, service account, resolved
   connected repository, full source SHA, branch and successful mandatory steps.
   Payload claims and a manually supplied SHA are insufficient evidence.
4. The updater checks that the commit is still an ancestor of canonical `t3`,
   then processes the private downstream registry. It never executes code from
   downloaded source or downstream checkouts. Git hooks and external protocols
   are disabled, and each repository receives a separate installation token.

The updater build's source, build configuration and container image are pinned
independently of the validated application revision. Changing the worker requires
reviewing a new worker commit and updating both trigger pins. PR validation has
no access to the GitHub App key, downstream registry or deployment credentials.

## Supported downstream layouts

| Mode | Update | History |
| --- | --- | --- |
| `merge` | Fast-forward the clean mirror, merge the exact source into an update branch, and update `integrations/downstream.json` | Keep source ancestry; the downstream PR uses a merge commit |
| `lock` | Change only `commit` in `upstream.lock.json` | Preserve private overlay and upstream release metadata; normal feature PR history |

Both modes use one bot-owned branch, `sync/t3-updates`, and one open PR for the
integration branch. Repeated events do not duplicate PRs. Older build events do
not roll the pin backwards. A pending update can receive a newer validated
commit without forcing the branch. Ref races retry from freshly fetched state;
continued races fail visibly rather than overwrite changes.

Before activation, inventory existing downstream update jobs and consolidate or
retire any writer targeting the same integration branch. This updater refuses a
separately open `sync/t3-*` PR rather than competing with it. Repository policy
files alone are not an inventory of external scheduled jobs.

The final generated commit has an HMAC-authenticated trailer binding its tree,
parents, source and destination. It lets a rerun recover after a branch push
without trusting an editable PR description. A human commit, altered tree,
unknown branch, conflicting merge or separately open manual sync PR stops the
update. Closing a bot PR without merging also stops automatic reuse. Resolve
that PR or retire its branch deliberately before resuming. Key rotation likewise
requires completing or retiring pending branches signed with the previous key.

Incoming changes to `.github/workflows/` require separate fork review. During
an upstream sync, keep every new or changed non-CI workflow parked under
`.github/workflows-disabled/`; only reviewed check workflows may remain active.
The bot does not request workflow-write permission or activate inherited workflows.

## Validation definition

`ci/cloudbuild.platform-validate.yaml` checks the actual checkout SHA, builds an
isolated tools image, runs the updater's regression tests and invokes
`ci/platform-checks.sh`. That script installs frozen dependencies, starts its
own disposable PostgreSQL/pgvector and MinIO resources, and runs migrations,
the repository's `make check` gates and the email contracts. No model credential
is configured. The tools image is built in Cloud Build and is not published.

`make check` covers backend/frontend checks and coverage, the production frontend
build, documentation and dependency/license audits. It excludes browser E2E;
do not describe this gate as a passed browser journey or deployed application.
The script also explicitly verifies the database-dependent checks so their
optional local behavior cannot silently qualify a central build.

## Private installation configuration

Use `ci/downstream-sync.example.json` as a schema example. Its zero application
IDs intentionally fail validation. Put real client repository names, branch
names, GitHub App IDs and Google resource names in a private configuration file
ending in `.downstream-sync.private.json`, then store its bytes in Secret Manager
as `t3os-downstream-config`. Store the PEM key separately as
`t3os-github-app-private-key`. Never commit either file or paste key values into
build substitutions, logs or command arguments.

Install a dedicated GitHub App on the source and selected downstream repositories.
Grant contents read/write and pull requests read/write. The worker narrows its
source token to contents read and each destination token to one repository. It
does not request checks/status write, workflow write, deployment or administration
write. To use optional auto-merge, grant administration **read** so it can verify
the destination's branch protection.

The source and destination must belong to the configured installation. The
installation token response is checked against the exact repository name.

## Google Cloud setup

Use an existing approved build project and regional GitHub connection. Connect
this public repository as a second-generation Cloud Build repository. Create
separate runtime identities:

| Identity | Required access | Excluded access |
| --- | --- | --- |
| Validator | Build logs and source retrieval required by its trigger | Bot secrets, GitHub write, image publishing and deployment |
| Updater | Build logs, `cloudbuild.builds.get`, and accessor on the two named secrets | Build submission, service-account impersonation, image publishing and deployment |

The project administrator and Cloud Build service agent provision/run triggers;
the validator and updater runtime accounts are not administrators. Ensure the
`cloud-builds` and `t3os-platform-validations` topics and Cloud Build service agent
notification permissions exist. The updater still verifies the actual validator
trigger through the API; publication to a topic is not proof of successful CI.
Use repository-scoped source access where the connection requires it.

Prepare a reviewed updater container containing `gcloud`, Python 3.12 or newer,
Git and OpenSSL, and resolve its immutable image digest. The updater configuration
checks those executables before consuming the event. Use an existing approved
Google Cloud CLI image only after verifying that tool contract. It does not
install tools while holding the GitHub key.

Render the validator definitions first (all values below are placeholders):

```bash
python3 ci/render_sync_triggers.py \
  --project YOUR_PROJECT --region YOUR_REGION \
  --repository-resource projects/YOUR_PROJECT/locations/YOUR_REGION/connections/YOUR_CONNECTION/repositories/YOUR_REPOSITORY \
  --validator-account t3os-validator@YOUR_PROJECT.iam.gserviceaccount.com \
  --updater-account t3os-updater@YOUR_PROJECT.iam.gserviceaccount.com \
  --updater-sha REVIEWED_FULL_COMMIT_SHA \
  --output-dir ci/generated-sync
```

Import `platform-pr.json` and `platform-push.json` using the regional Cloud Build
trigger import command. Observe the PR check and require it on the central `t3`
branch with the repository's reviewed-merge policy. Record the actual push-trigger ID and successful build
evidence; configure the same identity and repository resource in the private
registry. Rerun the renderer with `--validator-trigger-id ACTUAL_ID` and
`--updater-image APPROVED_IMAGE@sha256:ACTUAL_DIGEST` to produce the pinned
`downstream-updater.json`, then import it. Read back every trigger and verify its
account, event filter and immutable worker pins before calling it enabled.

```bash
gcloud builds triggers import --project YOUR_PROJECT --region YOUR_REGION \
  --source ci/generated-sync/platform-pr.json
gcloud builds triggers import --project YOUR_PROJECT --region YOUR_REGION \
  --source ci/generated-sync/platform-push.json
gcloud builds triggers import --project YOUR_PROJECT --region YOUR_REGION \
  --source ci/generated-sync/downstream-updater.json
```

For an initial already-merged source change, run the validator trigger for that
exact source revision. If the revision predates these CI files, first integrate
the reviewed CI implementation; do not pretend an old checkout contained it.
Use the newer validated platform revision that includes the approved change.
Cloud Build source provenance must resolve to the same full SHA as the checked
Git tree; a synthetic PR merge revision is not the PR head revision.

## Automatic merging and release

Start the first run with `auto_merge: false`. Observe the actual downstream PR
check name and its GitHub App ID. Set a strict required check on the destination
integration branch, enable repository auto-merge, and record the exact
`{"context": "observed name", "app_id": 12345}` in private `required_checks`.
Then `auto_merge: true` enables GitHub's native auto-merge. The worker verifies
that those producer-bound checks are actually required and that the branch must
be current. A missing protection rule, wrong producer or unavailable setting
leaves the PR open; there is no direct merge or bypass fallback. Existing review
requirements remain GitHub's responsibility and are not weakened.

Application release pipelines build from the merged downstream commit. Source
propagation does not turn on candidate delivery, perform production promotion,
send an email or invoke a paid model. Record the downstream commit, platform pin,
build ID and image digests in each application's release evidence.

## Acceptance and recovery

Verify one connected central validator run and both resulting downstream PRs.
Confirm repeated delivery keeps the same PRs, a newer validated source updates
them, human branch edits remain untouched, failed checks block merging, and the
merge-mode PR retains source ancestry. Inspect the exact resulting Cloud Build
run rather than the latest unrelated build in a project.

Failed updates are reported in the updater build log. Pub/Sub event delivery is
not a retry guarantee for a build that already started and failed. After fixing
the cause, replay the original successful validator notification or rerun that
validator for the same commit. Bounded concurrent-ref retries happen inside the
worker. Do not change the worker to accept a fabricated validation receipt.

Authoritative API references:

- [Cloud Build Pub/Sub triggers and substitution filters](https://docs.cloud.google.com/build/docs/automate-builds-pubsub-events)
- [Build notification payload](https://docs.cloud.google.com/build/docs/subscribe-build-notifications)
- [Build resource and resolved source provenance](https://docs.cloud.google.com/build/docs/api/reference/rest/v1/projects.builds)
- [Trigger resource and source/configuration pins](https://docs.cloud.google.com/build/docs/api/reference/rest/v1/projects.triggers)
- [GitHub installation tokens and repository scoping](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)
