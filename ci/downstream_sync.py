#!/usr/bin/env python3
"""Open downstream updates from an independently verified Cloud Build result.

The executable and its Cloud Build configuration must be pinned to a reviewed
commit. Downloaded repositories are data: this process never runs their code.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import TypeAlias
from zoneinfo import ZoneInfo

Json: TypeAlias = None | bool | int | float | str | list["Json"] | dict[str, "Json"]
Object: TypeAlias = dict[str, Json]
BRANCH = "sync/t3-updates"
STATE_PREFIX = "T3OS-Sync-State: "
SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class Refused(RuntimeError):
    """The requested update lacks sufficient evidence to proceed."""


class ConcurrentUpdate(Refused):
    """Another writer advanced a ref; retry with fresh signed branch state."""


class ApiError(Refused):
    def __init__(self, method: str, path: str, status: int) -> None:
        super().__init__(f"{method} {path} returned HTTP {status}")
        self.status = status


def obj(value: Json, label: str) -> Object:
    if not isinstance(value, dict):
        raise Refused(f"{label} must be an object")
    return value


def string(value: Json, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Refused(f"{label} must be a nonempty string")
    return value


def full_sha(value: Json) -> str:
    result = string(value, "commit")
    if not SHA.fullmatch(result):
        raise Refused("A full lowercase commit SHA is required")
    return result


def repo_name(value: Json) -> str:
    result = string(value, "repository")
    if not REPOSITORY.fullmatch(result) or any(
        part in {".", ".."} for part in result.split("/")
    ):
        raise Refused("Repository must be an owner/name, without a URL or credentials")
    return result


def branch_name(value: Json) -> str:
    result = string(value, "branch")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", result):
        raise Refused("Invalid branch name")
    if any(part in result for part in ("..", "//", "@{")) or result.endswith(
        ("/", ".", ".lock")
    ):
        raise Refused("Invalid branch name")
    return result


def canonical_url(repository: str) -> str:
    return f"https://github.com/{repo_name(repository)}.git"


def matches_repository(value: Json, repository: str) -> bool:
    return value in {
        canonical_url(repository),
        canonical_url(repository).removesuffix(".git"),
    }


def load_config(raw: str) -> Object:
    config = obj(json.loads(raw), "configuration")
    if config.get("schema_version") != 1:
        raise Refused("Unsupported configuration version")
    source = obj(config.get("source"), "source")
    repo_name(source.get("repository"))
    branch_name(source.get("branch"))
    validation = obj(config.get("validation"), "validation")
    for key in ("project", "region", "trigger_id"):
        if not IDENTIFIER.fullmatch(string(validation.get(key), key)):
            raise Refused(f"Invalid validation {key}")
    resource = string(validation.get("repository_resource"), "repository_resource")
    prefix = f"projects/{validation['project']}/locations/{validation['region']}/connections/"
    if not resource.startswith(prefix) or not re.fullmatch(
        r"projects/[^/]+/locations/[^/]+/connections/[^/]+/repositories/[^/]+", resource
    ):
        raise Refused(
            "Validation repository must belong to the configured project and region"
        )
    account = string(validation.get("service_account"), "service_account")
    if not account.startswith(f"projects/{validation['project']}/serviceAccounts/"):
        raise Refused("Validation identity must belong to the configured project")
    steps = validation.get("required_steps")
    if (
        not isinstance(steps, list)
        or not steps
        or any(not isinstance(step, str) or not step for step in steps)
    ):
        raise Refused("Validation must require explicitly named build steps")
    app = obj(config.get("github_app"), "github_app")
    for key in ("app_id", "installation_id"):
        if type(app.get(key)) is not int or app[key] <= 0:
            raise Refused(f"A real GitHub {key} is required")
    string(app.get("slug"), "GitHub App slug")
    targets = config.get("downstreams")
    if not isinstance(targets, list) or not targets:
        raise Refused("No private downstream configuration supplied")
    seen: set[str] = set()
    for item in targets:
        target = obj(item, "downstream")
        repository = repo_name(target.get("repository"))
        if (
            repository.lower() in seen
            or repository.lower() == str(source["repository"]).lower()
        ):
            raise Refused("Duplicate downstream or source used as a downstream")
        seen.add(repository.lower())
        base = branch_name(target.get("base_branch"))
        if base == BRANCH:
            raise Refused("The integration branch cannot be the bot branch")
        if target.get("mode") not in {"merge", "lock"}:
            raise Refused("Unknown downstream mode")
        if target.get("mode") == "merge":
            mirror = branch_name(target.get("mirror_branch"))
            if mirror in {base, BRANCH}:
                raise Refused("Mirror, integration and bot branches must be distinct")
        if type(target.get("auto_merge", False)) is not bool:
            raise Refused("auto_merge must be a boolean")
        if target.get("auto_merge"):
            checks = target.get("required_checks")
            if not isinstance(checks, list) or not checks:
                raise Refused(
                    "Auto-merge requires observed, producer-bound required checks"
                )
            for check in checks:
                check = obj(check, "required check")
                string(check.get("context"), "check context")
                if type(check.get("app_id")) is not int or check["app_id"] <= 0:
                    raise Refused(
                        "Required check producer must be a real GitHub App ID"
                    )
    return config


def request_json(method: str, url: str, token: str, data: Json = None) -> Json:
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )

    # Redirects must never forward either Google or GitHub credentials elsewhere.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(
            self,
            req: urllib.request.Request,
            fp: object,
            code: int,
            msg: str,
            headers: object,
            newurl: str,
        ) -> None:
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=45
        ) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        raise ApiError(method, urllib.parse.urlsplit(url).path, error.code) from None
    except urllib.error.URLError:
        raise Refused(
            f"{method} {urllib.parse.urlsplit(url).hostname} could not connect"
        ) from None
    if len(raw) > 8 * 1024 * 1024:
        raise Refused("API response exceeded the bounded response size")
    return json.loads(raw) if raw else None


def verified_source(build: Object, config: Object, build_id: str) -> str:
    policy = obj(config["validation"], "validation")
    source = obj(config["source"], "source")
    expected = {
        "id": build_id,
        "projectId": policy["project"],
        "buildTriggerId": policy["trigger_id"],
        "serviceAccount": policy["service_account"],
        "status": "SUCCESS",
    }
    if any(build.get(key) != value for key, value in expected.items()):
        raise Refused(
            "Build identity, trigger, validation account or successful result does not match"
        )
    resolved = obj(
        obj(build.get("sourceProvenance"), "source provenance").get(
            "resolvedConnectedRepository"
        ),
        "resolved connected repository",
    )
    if resolved.get("repository") != policy["repository_resource"]:
        raise Refused("Validation came from a different connected repository")
    sha = full_sha(resolved.get("revision"))
    substitutions = obj(build.get("substitutions"), "build substitutions")
    if (
        substitutions.get("BRANCH_NAME") != source["branch"]
        or substitutions.get("_SOURCE_SHA") != sha
    ):
        raise Refused("Validation did not check the exact integration branch commit")
    steps = build.get("steps")
    if not isinstance(steps, list):
        raise Refused("Build step evidence is missing")
    for required in policy["required_steps"]:
        found = [
            obj(step, "build step")
            for step in steps
            if obj(step, "build step").get("id") == required
        ]
        if (
            len(found) != 1
            or found[0].get("status") != "SUCCESS"
            or found[0].get("allowFailure")
        ):
            raise Refused(f"Required validation step {required} did not succeed")
        if found[0].get("allowExitCodes"):
            raise Refused(f"Required validation step {required} permits nonzero exits")
    return sha


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class GitHub:
    def __init__(self, token: str) -> None:
        self.token = token

    def call(self, method: str, path: str, data: Json = None) -> Json:
        if not path.startswith("/") or path.startswith("//"):
            raise Refused("GitHub API path must be relative to api.github.com")
        return request_json(method, "https://api.github.com" + path, self.token, data)

    def pages(self, path: str) -> list[Object]:
        result: list[Object] = []
        for page in range(1, 101):
            response = self.call(
                "GET", f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}"
            )
            if not isinstance(response, list):
                raise Refused("Expected a paginated GitHub list")
            result.extend(obj(item, "GitHub list item") for item in response)
            if len(response) < 100:
                return result
        raise Refused("GitHub pagination exceeded its bound")

    def head(self, repository: str, branch: str) -> str:
        value = obj(
            self.call(
                "GET",
                f"/repos/{repository}/git/ref/heads/{urllib.parse.quote(branch, safe='')}",
            ),
            "ref",
        )
        return full_sha(obj(value.get("object"), "ref object").get("sha"))


def installation_client(
    config: Object, private_key: str, repository: str, *, write: bool
) -> GitHub:
    app = obj(config["github_app"], "github_app")
    now = int(time.time())
    message = (
        b64(b'{"alg":"RS256","typ":"JWT"}')
        + "."
        + b64(
            json.dumps(
                {"iat": now - 60, "exp": now + 480, "iss": str(app["app_id"])}
            ).encode()
        )
    )
    with tempfile.TemporaryDirectory(prefix="t3os-app-") as directory:
        key_path = Path(directory) / "key.pem"
        key_path.write_text(private_key)
        key_path.chmod(0o600)
        signature = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(key_path)],
            input=message.encode(),
            capture_output=True,
            check=True,
        ).stdout
    app_client = GitHub(message + "." + b64(signature))
    identity = obj(app_client.call("GET", "/app"), "GitHub App")
    if identity.get("id") != app["app_id"] or identity.get("slug") != app["slug"]:
        raise Refused("GitHub App identity does not match private configuration")
    permissions: Object = {"contents": "write" if write else "read"}
    if write:
        permissions["pull_requests"] = "write"
        # This permission is read-only and is used solely to verify merge gates.
        target = next(
            obj(t, "downstream")
            for t in config["downstreams"]
            if obj(t, "downstream")["repository"] == repository
        )
        if target.get("auto_merge"):
            permissions["administration"] = "read"
    response = obj(
        app_client.call(
            "POST",
            f"/app/installations/{app['installation_id']}/access_tokens",
            {
                "repositories": [repository.split("/", 1)[1]],
                "permissions": permissions,
            },
        ),
        "installation token",
    )
    actual = response.get("repositories")
    if (
        not isinstance(actual, list)
        or len(actual) != 1
        or obj(actual[0], "token repository").get("full_name") != repository
    ):
        raise Refused("GitHub token is not restricted to the intended repository")
    return GitHub(string(response.get("token"), "installation token"))


class Git:
    def __init__(self, directory: Path, *, allow_local: bool = False) -> None:
        self.directory = directory
        self.allow_local = allow_local  # Test fixtures only; production config accepts GitHub owner/name values.
        self.auth: dict[str, str] = {}

    def run(
        self, *args: str, check: bool = True, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        keep = {
            "PATH",
            "TMPDIR",
            "SYSTEMROOT",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "CURL_CA_BUNDLE",
            "REQUESTS_CA_BUNDLE",
        }
        env = {key: value for key, value in os.environ.items() if key in keep}
        env.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": "/bin/false",
                "GIT_AUTHOR_NAME": "T3OS update bot",
                "GIT_AUTHOR_EMAIL": "t3os-update@users.noreply.github.com",
                "GIT_COMMITTER_NAME": "T3OS update bot",
                "GIT_COMMITTER_EMAIL": "t3os-update@users.noreply.github.com",
            }
        )
        env["GIT_CONFIG_COUNT"] = str(len(self.auth))
        for number, (url, token) in enumerate(self.auth.items()):
            env[f"GIT_CONFIG_KEY_{number}"] = f"http.{url}.extraheader"
            env[f"GIT_CONFIG_VALUE_{number}"] = (
                "Authorization: Basic "
                + base64.b64encode(f"x-access-token:{token}".encode()).decode()
            )
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "protocol.ext.allow=never",
                "-c",
                f"protocol.file.allow={'always' if self.allow_local else 'never'}",
                *args,
            ],
            check=False,
            cwd=self.directory,
            env=env,
            text=True,
            input=input_text,
            capture_output=True,
            timeout=300,
        )
        if check and result.returncode:
            # Git stderr can contain remote-controlled text; keep tokens and remote output out of logs.
            raise Refused(
                f"git {args[0]} failed ({result.returncode}); no automatic conflict resolution or forced push"
            )
        return result

    def text(self, *args: str) -> str:
        return self.run(*args).stdout.strip()

    def ancestor(self, earlier: str, later: str) -> bool:
        result = self.run("merge-base", "--is-ancestor", earlier, later, check=False)
        if result.returncode not in {0, 1}:
            raise Refused("Git ancestry could not be established")
        return result.returncode == 0


def sign_state(state: Object, key: str) -> str:
    payload = b64(json.dumps(state, sort_keys=True, separators=(",", ":")).encode())
    signature = hmac.new(
        key.encode(), ("t3os-sync-v1:" + payload).encode(), hashlib.sha256
    ).hexdigest()
    return payload + "." + signature


def read_state(git: Git, sha: str, key: str, repository: str) -> Object:
    trailers = [
        line[len(STATE_PREFIX) :]
        for line in git.text("show", "-s", "--format=%B", sha).splitlines()
        if line.startswith(STATE_PREFIX)
    ]
    if len(trailers) != 1:
        raise Refused(
            "Existing update branch is not signed by this updater; preserve it for review"
        )
    try:
        payload, signature = trailers[0].split(".")
        expected = hmac.new(
            key.encode(), ("t3os-sync-v1:" + payload).encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        state = obj(
            json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))),
            "signed state",
        )
    except (ValueError, TypeError):
        raise Refused(
            "Existing update branch has an invalid ownership signature"
        ) from None
    parents = git.text("show", "-s", "--format=%P", sha).split()
    if (
        state.get("repository") != repository
        or state.get("branch") != BRANCH
        or state.get("tree") != git.text("rev-parse", f"{sha}^{{tree}}")
        or state.get("parents") != parents
    ):
        raise Refused("Signed updater state does not describe the actual commit")
    full_sha(state.get("source_sha"))
    return state


def read_metadata(git: Git, target: Object, source: Object) -> tuple[Path, Object, str]:
    path = git.directory / (
        "integrations/downstream.json"
        if target["mode"] == "merge"
        else "upstream.lock.json"
    )
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(git.directory.resolve())
    ):
        raise Refused(
            "Downstream metadata must be a regular tracked file inside the checkout"
        )
    if not git.text("ls-files", "--", str(path.relative_to(git.directory))):
        raise Refused("Downstream metadata is not tracked")
    metadata = obj(json.loads(path.read_text()), "downstream metadata")
    if metadata.get("schema_version") != 1:
        raise Refused("Unsupported downstream metadata schema")
    parent = (
        obj(metadata.get("parent"), "parent") if target["mode"] == "merge" else metadata
    )
    if not matches_repository(parent.get("repository"), str(source["repository"])):
        raise Refused("Downstream is pinned to a different platform repository")
    if target["mode"] == "merge" and parent.get("branch") != source["branch"]:
        raise Refused("Downstream is pinned to a different platform branch")
    return path, metadata, full_sha(parent.get("commit"))


def prepare_commit(
    git: Git, target: Object, source: Object, source_sha: str, base_sha: str, key: str
) -> str | None:
    path, metadata, previous = read_metadata(git, target, source)
    old_head = git.text("rev-parse", "HEAD")
    if target["mode"] == "merge" and not git.ancestor(previous, old_head):
        raise Refused(
            "Fork metadata claims platform ancestry absent from its actual history"
        )
    if previous != source_sha and git.ancestor(source_sha, previous):
        return None
    if previous == source_sha and git.ancestor(base_sha, old_head):
        return None
    if not git.ancestor(previous, source_sha):
        raise Refused("Platform pin diverged; refusing a rollback or unrelated history")
    if target["mode"] == "merge":
        changed = git.text(
            "diff", "--name-only", previous, source_sha, "--", ".github/workflows/"
        )
        if changed:
            raise Refused(
                "Incoming workflow changes require separate review before a fork sync"
            )
    merge_refs = [
        ref
        for ref in [base_sha, *([source_sha] if target["mode"] == "merge" else [])]
        if not git.ancestor(ref, old_head)
    ]
    if merge_refs:
        git.run("merge", "--no-commit", "--no-ff", *merge_refs)
    # A base merge may change metadata; reread it instead of overwriting client changes.
    path, metadata, current = read_metadata(git, target, source)
    if current != previous and current != source_sha:
        raise Refused("Base movement changed the platform pin; retry from fresh state")
    if target["mode"] == "merge":
        obj(metadata["parent"], "parent")["commit"] = source_sha
        timezone = string(metadata.get("timezone", "UTC"), "timezone")
        metadata["selected_on"] = datetime.now(ZoneInfo(timezone)).date().isoformat()
        metadata["compatibility"] = {
            "status": "not_tested",
            "reason": "Downstream CI must validate this update.",
            "evidence": [],
        }
    else:
        metadata["commit"] = source_sha
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    git.run("add", "--", str(path.relative_to(git.directory)))
    tree = git.text("write-tree")
    merge_head = git.directory / ".git/MERGE_HEAD"
    parents = [
        old_head,
        *(merge_head.read_text().splitlines() if merge_head.exists() else []),
    ]
    state: Object = {
        "repository": target["repository"],
        "branch": BRANCH,
        "source_repository": source["repository"],
        "source_sha": source_sha,
        "base_sha": base_sha,
        "tree": tree,
        "parents": parents,
    }
    arguments = ["commit-tree", tree]
    for parent in parents:
        arguments.extend(["-p", parent])
    new_head = git.text(
        *arguments,
        "-m",
        f"chore(sync): update platform to {source_sha[:12]}\n\n{STATE_PREFIX}{sign_state(state, key)}",
    )
    git.run("reset", "--hard", new_head)
    return new_head


def enable_auto_merge(api: GitHub, repository: str, target: Object, pr: Object) -> None:
    protection = obj(
        api.call(
            "GET",
            f"/repos/{repository}/branches/{urllib.parse.quote(str(target['base_branch']), safe='')}/protection",
        ),
        "branch protection",
    )
    required = obj(protection.get("required_status_checks"), "required status checks")
    actual_checks = required.get("checks")
    if required.get("strict") is not True or not isinstance(actual_checks, list):
        raise Refused("Auto-merge requires strict, producer-bound branch protection")
    for expected in target["required_checks"]:
        if expected not in actual_checks:
            raise Refused(
                "Observed required checks are not enforced by branch protection"
            )
    if pr.get("draft"):
        raise Refused("Do not enable auto-merge on a draft PR")
    method = "MERGE" if target["mode"] == "merge" else "SQUASH"
    result = obj(
        api.call(
            "POST",
            "/graphql",
            {
                "query": "mutation($id:ID!,$method:PullRequestMergeMethod!){enablePullRequestAutoMerge(input:{pullRequestId:$id,mergeMethod:$method}){pullRequest{number}}}",
                "variables": {"id": pr["node_id"], "method": method},
            },
        ),
        "auto-merge result",
    )
    if result.get("errors"):
        raise Refused("GitHub did not enable auto-merge; the PR remains open")


def managed_description(previous: str, body: str) -> str:
    begin, end = "<!-- t3os-sync:begin -->", "<!-- t3os-sync:end -->"
    replacement = f"{begin}\n{body}{end}"
    if not previous:
        return replacement
    if (
        previous.count(begin) != 1
        or previous.count(end) != 1
        or previous.index(begin) > previous.index(end)
    ):
        raise Refused("The PR's managed description was edited; preserve it for review")
    return (
        previous[: previous.index(begin)]
        + replacement
        + previous[previous.index(end) + len(end) :]
    )


def sync_target(
    config: Object,
    target: Object,
    source_sha: str,
    private_key: str,
    source_api: GitHub,
    api: GitHub,
) -> str:
    source = obj(config["source"], "source")
    repository = str(target["repository"])
    source_repository = str(source["repository"])
    base = str(target["base_branch"])
    bot_login = str(obj(config["github_app"], "app")["slug"]) + "[bot]"
    pulls = api.pages(
        f"/repos/{repository}/pulls?state=open&base={urllib.parse.quote(base, safe='')}"
    )
    sync_pulls = [
        pr
        for pr in pulls
        if str(obj(pr.get("head"), "PR head").get("ref", "")).startswith("sync/t3-")
    ]
    if len(sync_pulls) > 1 or any(
        obj(pr["head"], "head").get("ref") != BRANCH for pr in sync_pulls
    ):
        raise Refused("An existing manual or duplicate sync PR must be resolved first")
    pr = sync_pulls[0] if sync_pulls else None
    if pr and (
        obj(pr.get("user"), "PR author").get("login") != bot_login
        or obj(obj(pr["head"], "head").get("repo"), "head repo").get("full_name")
        != repository
    ):
        raise Refused(
            "Existing update PR is not owned by the configured bot and repository"
        )
    with tempfile.TemporaryDirectory(prefix="t3os-downstream-") as directory:
        git = Git(Path(directory))
        git.run("init", "-q")
        git.auth = {
            canonical_url(repository): api.token,
            canonical_url(source_repository): source_api.token,
        }
        git.run("remote", "add", "origin", canonical_url(repository))
        git.run("remote", "add", "platform", canonical_url(source_repository))
        git.run(
            "fetch",
            "--no-tags",
            "origin",
            f"refs/heads/{base}:refs/remotes/origin/base",
        )
        base_sha = git.text("rev-parse", "refs/remotes/origin/base")
        git.run(
            "fetch",
            "--no-tags",
            "platform",
            f"refs/heads/{source['branch']}:refs/remotes/platform/source",
        )
        if not git.ancestor(source_sha, "refs/remotes/platform/source"):
            raise Refused("Validated SHA is not on the canonical platform branch")
        if pr is None:
            git.run("checkout", "-q", "--detach", base_sha)
            _, _, integrated_pin = read_metadata(git, target, source)
            if target["mode"] == "merge" and not git.ancestor(integrated_pin, base_sha):
                raise Refused(
                    "Integration metadata claims platform ancestry absent from its history"
                )
            if integrated_pin == source_sha or git.ancestor(source_sha, integrated_pin):
                return f"{repository}: already integrated {source_sha[:12]}"
        branch_ref = git.text("ls-remote", "--heads", "origin", f"refs/heads/{BRANCH}")
        if branch_ref:
            git.run(
                "fetch",
                "--no-tags",
                "origin",
                f"refs/heads/{BRANCH}:refs/remotes/origin/update",
            )
            head = git.text("rev-parse", "refs/remotes/origin/update")
            state = read_state(git, head, private_key, repository)
            if state.get("source_repository") != source_repository:
                raise Refused("Existing branch belongs to a different platform")
            if pr and obj(pr["head"], "PR head").get("sha") != head:
                raise ConcurrentUpdate("Update branch moved during inspection")
            if not pr:
                history = api.pages(
                    f"/repos/{repository}/pulls?state=closed&head={repository.split('/')[0]}:{BRANCH}&base={urllib.parse.quote(base, safe='')}"
                )
                if history and history[0].get("merged_at") is None:
                    raise Refused(
                        "The previous sync PR was closed without merging; preserve that decision"
                    )
        else:
            head = base_sha
        git.run("checkout", "-q", "-b", BRANCH, head)
        if branch_ref:
            _, _, branch_pin = read_metadata(git, target, source)
            if branch_pin != state["source_sha"]:
                raise Refused("Signed state and downstream metadata disagree")
        new_head = prepare_commit(
            git, target, source, source_sha, base_sha, private_key
        )
        if new_head is None and not branch_ref:
            return f"{repository}: already includes {source_sha[:12]}"
        if new_head is None:
            state = read_state(git, head, private_key, repository)
            source_sha = full_sha(state["source_sha"])
            if git.ancestor(head, base_sha) and not pr:
                return f"{repository}: already integrated"
        else:
            head = new_head
        if api.head(repository, base) != base_sha:
            raise ConcurrentUpdate("Integration branch advanced during preparation")
        if target["mode"] == "merge":
            mirror = str(target["mirror_branch"])
            git.run(
                "fetch",
                "--no-tags",
                "origin",
                f"refs/heads/{mirror}:refs/remotes/origin/mirror",
            )
            if not git.ancestor("refs/remotes/origin/mirror", source_sha):
                if not git.ancestor(source_sha, "refs/remotes/origin/mirror"):
                    raise Refused("Mirror diverged; a forced update is forbidden")
            else:
                if git.run(
                    "push", "origin", f"{source_sha}:refs/heads/{mirror}", check=False
                ).returncode:
                    raise ConcurrentUpdate("Mirror changed during its fast-forward")
        if (
            new_head
            and git.run(
                "push", "origin", f"{head}:refs/heads/{BRANCH}", check=False
            ).returncode
        ):
            raise ConcurrentUpdate("Update branch changed during its non-forced push")
        if api.head(repository, BRANCH) != head:
            raise ConcurrentUpdate("Update branch changed after push")
        body = (
            f"Update the platform to `{source_sha}` from `{source_repository}:{source['branch']}`.\n\n"
            f"Prepared against `{base_sha}`. Downstream checks must validate this PR before merge. "
            "This update does not deploy a running service.\n\n"
            + (
                "Merge this sync PR with a merge commit to preserve platform ancestry.\n"
                if target["mode"] == "merge"
                else "The private overlay and upstream release metadata are preserved.\n"
            )
        )
        if pr is None:
            # GitHub rejects duplicate open PRs with the same head/base; normal pushes serialize writers.
            try:
                pr = obj(
                    api.call(
                        "POST",
                        f"/repos/{repository}/pulls",
                        {
                            "title": f"chore(sync): update T3OS to {source_sha[:12]}",
                            "head": BRANCH,
                            "base": base,
                            "body": managed_description("", body),
                            "maintainer_can_modify": False,
                        },
                    ),
                    "created PR",
                )
            except ApiError as error:
                if error.status in {409, 422}:
                    raise ConcurrentUpdate(
                        "PR creation raced with another update; inspect fresh state"
                    ) from None
                raise
        elif new_head:
            fresh_pr = obj(
                api.call("GET", f"/repos/{repository}/pulls/{pr['number']}"),
                "current PR",
            )
            if (
                fresh_pr.get("state") != "open"
                or obj(fresh_pr.get("head"), "PR head").get("sha") != head
            ):
                raise ConcurrentUpdate("PR changed before its metadata update")
            pr = obj(
                api.call(
                    "PATCH",
                    f"/repos/{repository}/pulls/{pr['number']}",
                    {
                        "title": f"chore(sync): update T3OS to {source_sha[:12]}",
                        "body": managed_description(
                            str(fresh_pr.get("body", "")), body
                        ),
                    },
                ),
                "updated PR",
            )
        if target.get("auto_merge"):
            enable_auto_merge(api, repository, target, pr)
        return f"{repository}: {pr['html_url']} at {head}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-id",
        required=True,
        help="Completed central validation build ID from the event",
    )
    arguments = parser.parse_args()
    if not IDENTIFIER.fullmatch(arguments.build_id):
        raise Refused("Invalid build ID")
    config = load_config(os.environ["T3OS_DOWNSTREAM_CONFIG"])
    policy = obj(config["validation"], "validation")
    google_token = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    build = obj(
        request_json(
            "GET",
            f"https://cloudbuild.googleapis.com/v1/projects/{policy['project']}/locations/{policy['region']}/builds/{arguments.build_id}",
            google_token,
        ),
        "build",
    )
    source_sha = verified_source(build, config, arguments.build_id)
    private_key = os.environ.pop("T3OS_GITHUB_APP_PRIVATE_KEY")
    source_api = installation_client(
        config,
        private_key,
        str(obj(config["source"], "source")["repository"]),
        write=False,
    )
    failures: list[str] = []
    for item in config["downstreams"]:
        target = obj(item, "downstream")
        try:
            api = installation_client(
                config, private_key, str(target["repository"]), write=True
            )
            for attempt in range(3):
                try:
                    print(
                        sync_target(
                            config, target, source_sha, private_key, source_api, api
                        )
                    )
                    break
                except ConcurrentUpdate:
                    if attempt == 2:
                        raise
        except Refused as error:
            failures.append(f"{target['repository']}: {error}")
    for failure in failures:
        print(f"BLOCKED: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        Refused,
        KeyError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        # Exception text from subprocess may include command arguments; report only its class there.
        print(
            f"BLOCKED: {error if isinstance(error, Refused) else type(error).__name__}"
        )
        raise SystemExit(1) from None
