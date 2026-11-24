"""Render concrete Cloud Build triggers without changing cloud resources."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def render(args: argparse.Namespace) -> dict[str, dict]:
    if not re.fullmatch(r"[0-9a-f]{40}", args.updater_sha):
        raise ValueError("The updater must be pinned to a reviewed full commit SHA")
    prefix = f"projects/{args.project}/locations/{args.region}/connections/"
    if not args.repository_resource.startswith(prefix) or not re.fullmatch(
        r"projects/[^/]+/locations/[^/]+/connections/[^/]+/repositories/[^/]+",
        args.repository_resource,
    ):
        raise ValueError(
            "Connected repository must be in the specified project and region"
        )
    for account in (args.validator_account, args.updater_account):
        if not re.fullmatch(
            r"[a-z0-9-]+@" + re.escape(args.project) + r"\.iam\.gserviceaccount\.com",
            account,
        ):
            raise ValueError("Service accounts must belong to the specified project")
    if args.validator_account == args.updater_account:
        raise ValueError("Validation and updater identities must be different")
    config_source = {
        "path": "ci/cloudbuild.platform-validate.yaml",
        "repoType": "GITHUB",
        "repository": args.repository_resource,
        "revision": args.updater_sha,
    }
    common = {
        "serviceAccount": f"projects/{args.project}/serviceAccounts/{args.validator_account}",
        "gitFileSource": config_source,
        "substitutions": {"_SOURCE_SHA": "${COMMIT_SHA}"},
        "includeBuildLogs": "INCLUDE_BUILD_LOGS_WITH_STATUS",
    }
    triggers = {
        "platform-push": {
            **common,
            "name": "t3os-platform-validated",
            "substitutions": {
                "_SOURCE_SHA": "${COMMIT_SHA}",
                "_NOTIFICATION_TOPIC": "t3os-platform-validations",
            },
            "repositoryEventConfig": {
                "repository": args.repository_resource,
                "push": {"branch": "^t3$"},
            },
        },
        "platform-pr": {
            **common,
            "name": "t3os-platform-pr",
            "repositoryEventConfig": {
                "repository": args.repository_resource,
                "pullRequest": {
                    "branch": "^t3$",
                    "commentControl": "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY",
                },
            },
        },
    }
    if args.validator_trigger_id:
        if not re.fullmatch(r"[A-Za-z0-9-]+", args.validator_trigger_id):
            raise ValueError("Invalid validator trigger ID")
        if not args.updater_image or not re.fullmatch(
            r"[a-z0-9./_-]+@sha256:[0-9a-f]{64}", args.updater_image
        ):
            raise ValueError("The privileged updater image must be pinned by digest")
        # Pub/Sub trigger filters reference substitutions, not notifier `build.*` fields.
        triggers["downstream-updater"] = {
            "name": "t3os-downstream-sync",
            "serviceAccount": f"projects/{args.project}/serviceAccounts/{args.updater_account}",
            "description": f"Verify successful platform validation against trigger {args.validator_trigger_id}",
            "pubsubConfig": {
                "topic": f"projects/{args.project}/topics/t3os-platform-validations"
            },
            "filter": '_STATUS == "SUCCESS"',
            "sourceToBuild": {
                "repository": args.repository_resource,
                "ref": args.updater_sha,
                "repoType": "GITHUB",
            },
            "gitFileSource": {
                "repository": args.repository_resource,
                "revision": args.updater_sha,
                "path": "ci/cloudbuild.downstream-updater.yaml",
                "repoType": "GITHUB",
            },
            "substitutions": {
                "_SOURCE_BUILD_ID": "$(body.message.attributes.buildId)",
                "_STATUS": "$(body.message.attributes.status)",
                "_UPDATER_IMAGE": args.updater_image,
            },
        }
    return triggers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in (
        "project",
        "region",
        "repository-resource",
        "validator-account",
        "updater-account",
        "updater-sha",
        "output-dir",
    ):
        parser.add_argument(f"--{argument}", required=True)
    parser.add_argument("--validator-trigger-id")
    parser.add_argument("--updater-image")
    args = parser.parse_args()
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, trigger in render(args).items():
        path = directory / f"{name}.json"
        path.write_text(json.dumps(trigger, indent=2) + "\n")
        path.chmod(0o600)
        print(path)


if __name__ == "__main__":
    main()
