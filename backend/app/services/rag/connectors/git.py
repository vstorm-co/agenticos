"""Git sync connector: a repository's documentation, over HTTPS, with a token.

GitHub and GitLab are one connector, because what it needs is a clone URL and a
token rather than either platform's API (#987). The token is an `ApiKeySecret`
in the organization's vault, sent as a basic-auth header - both platforms take a
personal access token as the password under any user name.

**What a sync costs.** The expensive half of a sync is parsing and embedding, and
the content hash already spares an unchanged file both (#990). What is left is
the transfer, and this connector keeps it small twice over:

- `remote_version` answers the branch's head commit with one `git ls-remote`,
  about a kilobyte. The sync stores it, and a scheduled run that finds the same
  commit under the same configuration stops there - no clone at all.
- When the commit did move, the clone is shallow (`--depth 1`), partial
  (`--filter=blob:none`) and sparse: only the blobs the include patterns match
  are downloaded, so a monorepo's documentation costs its documentation and not
  its source tree.

**The URL is remote-chosen**, so it is pinned the way `app/core/pinned_http.py`
pins a request (#840, #860): the host is resolved and checked once by
`resolve_pinned_url`, and git is told to dial exactly those addresses through
`http.curloptResolve`, with redirects off. The same caveat applies as there: an
egress proxy from `HTTPS_PROXY` resolves the destination itself.

**Nothing the repository contains is trusted with more than its bytes.** Only
HTTPS is allowed as a transport - `protocol.allow=never` also closes `ext::` and
`file://` - symlinks are checked out as plain files and then left out of the
listing by their index mode, submodules are not followed, and no user or system
git configuration is read.
"""

import asyncio
import base64
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.exceptions import BadRequestError, ConfigurationError, ExternalServiceError
from app.core.sanitize import PinnedAddress, UrlRefusedError, resolve_pinned_url
from app.core.secret_kinds import ApiKeySecret, SecretKind, StorableSecret
from app.services.rag.connectors import (
    BaseSyncConnector,
    ConfigRefusal,
    ConnectorConfig,
    RemoteFile,
)

logger = logging.getLogger(__name__)

# `ls-remote` is one round trip; a clone of a large repository's documentation
# is minutes at most. Both bounds exist so a server that accepts the connection
# and then stalls cannot hold a worker for ever - `http.lowSpeedLimit` below
# catches the slower version of the same stall mid-transfer.
LS_REMOTE_TIMEOUT_SECONDS = 30.0
CLONE_TIMEOUT_SECONDS = 600.0

# Documentation, not the tree: a repository's source is not a corpus, and
# ingesting it is how a knowledge base fills with code nobody asked to search.
# Markdown and plain text are what every parser routes natively.
DEFAULT_INCLUDE = ["**/*.md", "**/*.txt"]

# A ref name as `git check-ref-format --branch` would take it, narrowed to what a
# branch is actually called. The leading-character rule is what matters most: a
# value starting with `-` would be read by git as an option.
_BRANCH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]{0,254}")
_PATH = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9._/ -]{0,1023}")

# Regular files only. `120000` is a symlink, `160000` a submodule's commit.
_FILE_MODES = frozenset({"100644", "100755"})

# Which stderr lines mean the credential, as opposed to the repository or the
# network. Matched to choose *our* sentence; git's own is logged and never stored,
# because it names the URL it failed on.
_AUTH_FAILURES = (
    "authentication failed",
    "could not read username",
    "could not read password",
    "http basic: access denied",
    "the requested url returned error: 401",
    "the requested url returned error: 403",
)
_NOT_FOUND = ("repository not found", "not found", "the requested url returned error: 404")


class GitConfig(BaseModel):
    """Where a repository's documentation is, and which of it to read.

    The token is not here - it is an API key the source names in `secret_id`
    (#937). Issue it for the one repository: a token that reads every private
    repository its owner can makes all of them searchable by whoever can read the
    collection (`docs/file-processing.md#who-ends-up-able-to-read-what-a-source-ingested`).
    """

    repository_url: str = Field(
        title="Repository URL",
        description="The HTTPS clone URL, e.g. https://github.com/acme/handbook.git",
    )
    branch: str = Field(default="main", title="Branch")
    path_prefix: str | None = Field(
        default=None,
        title="Path Prefix",
        description="e.g. 'docs' - leave empty for the whole repository",
    )
    include: list[str] = Field(
        default_factory=lambda: list(DEFAULT_INCLUDE),
        title="Include patterns",
        description=(
            "Which files to ingest, as .gitignore-style patterns relative to the path "
            "prefix. Defaults to Markdown and plain text."
        ),
    )

    @field_validator("repository_url")
    @classmethod
    def _https_clone_url(cls, value: str) -> str:
        """An HTTPS URL naming a repository, with nothing git would read as more.

        No userinfo, because a token in the URL is a token in every log line that
        quotes it - the vault is where it goes. No query or fragment, because a
        clone URL has neither and a value carrying one was pasted from somewhere
        else.
        """
        parts = urlsplit(value.strip())
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("The repository URL must be an https:// clone URL.")
        if parts.username is not None or parts.password is not None:
            raise ValueError(
                "The repository URL must not carry a user name or token. Put the token in "
                "the Vault and choose it as this source's credential."
            )
        if parts.query or parts.fragment:
            raise ValueError("The repository URL must not have a query string or a fragment.")
        if not parts.path.strip("/"):
            raise ValueError("The repository URL must name a repository, not only a host.")
        return value.strip()

    @field_validator("branch")
    @classmethod
    def _branch_name(cls, value: str) -> str:
        if not _BRANCH.fullmatch(value) or ".." in value or value.endswith((".lock", "/")):
            raise ValueError("That is not a branch name git would accept.")
        return value

    @field_validator("path_prefix")
    @classmethod
    def _relative_path(cls, value: str | None) -> str | None:
        """A directory inside the repository, or `None` for all of it."""
        stripped = (value or "").strip().strip("/")
        if not stripped:
            return None
        if not _PATH.fullmatch(stripped) or ".." in PurePosixPath(stripped).parts:
            raise ValueError("The path prefix must be a directory inside the repository.")
        # `./docs` and `docs//guides` spelled the way git's index spells them, or
        # the sparse pattern and the prefix match nothing.
        return str(PurePosixPath(stripped))

    @field_validator("include")
    @classmethod
    def _patterns(cls, value: list[str]) -> list[str]:
        """Patterns handed to `git sparse-checkout` one per line.

        A line break inside one would be a second pattern nobody typed, and a
        leading `!` would be an exclusion that the prefix anchoring below cannot
        express - both are refused rather than reinterpreted.
        """
        patterns = [pattern.strip().lstrip("/") for pattern in value if pattern.strip()]
        if not patterns:
            raise ValueError("At least one include pattern is needed.")
        for pattern in patterns:
            if "\n" in pattern or "\r" in pattern or pattern.startswith(("!", "#")):
                raise ValueError(f"The include pattern {pattern!r} is not one this source can use.")
        return patterns

    def sparse_patterns(self) -> list[str]:
        """The include patterns anchored under the prefix, as `sparse-checkout` reads them."""
        root = f"/{self.path_prefix}/" if self.path_prefix else "/"
        return [f"{root}{pattern}" for pattern in self.include]

    def repository(self) -> str:
        """`host/owner/repo` - what a `source_path` names the repository by."""
        parts = urlsplit(self.repository_url)
        path = parts.path.strip("/").removesuffix(".git")
        return f"{parts.hostname}/{path}"


class GitConnector(BaseSyncConnector):
    """A repository's documentation, cloned once per sync that has something to read.

    Holds the clone between `list_files` and the downloads that follow it, so an
    instance is one sync's and `aclose` removes what it made.
    """

    CONNECTOR_TYPE: ClassVar[str] = "git"
    DISPLAY_NAME: ClassVar[str] = "Git repository"
    SECRET_KIND: ClassVar[SecretKind] = SecretKind.API_KEY
    CONFIG_MODEL: ClassVar[type[BaseModel]] = GitConfig

    def __init__(self) -> None:
        self._workdir: Path | None = None
        self._checkout: Path | None = None

    async def validate_config(self, config: ConnectorConfig) -> ConfigRefusal | None:
        """The required fields, then every field's shape, then where the URL points.

        The address check runs here as well as at sync time so a URL naming an
        internal host is refused on the form that typed it, rather than an hour
        later in a sync log. It is repeated at sync time because a name can
        answer differently by then.
        """
        refusal = await super().validate_config(config)
        if refusal is not None:
            return refusal
        try:
            parsed = GitConfig.model_validate(config)
        except ValidationError as exc:
            error = exc.errors()[0]
            field = str(error["loc"][0]) if error["loc"] else None
            return ConfigRefusal(
                message=str(error["msg"]).removeprefix("Value error, "), field=field
            )
        try:
            await asyncio.to_thread(resolve_pinned_url, parsed.repository_url, frozenset({"https"}))
        except UrlRefusedError as exc:
            return ConfigRefusal(message=str(exc), field="repository_url")
        return None

    async def remote_version(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> str:
        """The branch's head commit, read without cloning anything.

        Raises:
            BadRequestError: no usable token, or the branch does not exist.
            ExternalServiceError: the repository could not be reached or read.
        """
        parsed = GitConfig.model_validate(config)
        env = await self._environment(parsed, credential)
        out = await self._git(
            "ls-remote",
            "--",
            parsed.repository_url,
            f"refs/heads/{parsed.branch}",
            env=env,
            timeout=LS_REMOTE_TIMEOUT_SECONDS,
        )
        line = out.strip().splitlines()[0] if out.strip() else ""
        if not line:
            raise BadRequestError(
                message=f"The repository has no branch named {parsed.branch!r}.",
                details={"branch": parsed.branch},
            )
        return line.split()[0]

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> list[RemoteFile]:
        """Clone what the include patterns match and answer every regular file in it."""
        parsed = GitConfig.model_validate(config)
        env = await self._environment(parsed, credential)
        await self.aclose()
        self._workdir = await asyncio.to_thread(_make_workdir)
        checkout = self._workdir / "repo"
        await self._git(
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--filter=blob:none",
            "--no-checkout",
            "--single-branch",
            "--no-tags",
            "--branch",
            parsed.branch,
            "--",
            parsed.repository_url,
            str(checkout),
            env=env,
            timeout=CLONE_TIMEOUT_SECONDS,
            cwd=self._workdir,
        )
        await self._git(
            "sparse-checkout",
            "set",
            "--no-cone",
            "--stdin",
            env=env,
            timeout=CLONE_TIMEOUT_SECONDS,
            cwd=checkout,
            stdin="\n".join(parsed.sparse_patterns()) + "\n",
        )
        await self._git("checkout", "--quiet", env=env, timeout=CLONE_TIMEOUT_SECONDS, cwd=checkout)
        self._checkout = checkout
        staged = await self._git("ls-files", "-z", "--stage", env=env, timeout=60.0, cwd=checkout)
        return await asyncio.to_thread(self._listing, checkout, staged, parsed)

    def listing_root(self, config: ConnectorConfig) -> str:
        """What every `source_path` this source lists begins with.

        The branch is part of it, so two sources reading two branches of one
        repository into one collection address different documents rather than
        replacing each other's.
        """
        parsed = GitConfig.model_validate(config)
        root = f"git://{parsed.repository()}@{parsed.branch}/"
        return f"{root}{parsed.path_prefix}/" if parsed.path_prefix else root

    async def aclose(self) -> None:
        """Remove the clone. Safe to call twice, and before anything was cloned."""
        workdir, self._workdir, self._checkout = self._workdir, None, None
        if workdir is not None:
            await asyncio.to_thread(shutil.rmtree, workdir, True)

    async def _fetch(
        self,
        file: RemoteFile,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        """Copy one checked-out file to the path the base class chose.

        Resolved and confirmed to be inside the checkout first. The listing only
        names regular files, so this is the second of two checks rather than the
        only one: a `RemoteFile` reaching here from anywhere else must not be able
        to name `../../etc/passwd`.
        """
        if self._checkout is None:
            raise RuntimeError("GitConnector._fetch called before list_files cloned anything")
        checkout = self._checkout
        named = checkout / file.id
        source = named.resolve()
        if named.is_symlink() or not source.is_relative_to(checkout.resolve()):
            raise BadRequestError(message="A repository file resolved outside its checkout.")
        await asyncio.to_thread(shutil.copyfile, source, dest_path)

    def _listing(self, checkout: Path, staged: str, parsed: GitConfig) -> list[RemoteFile]:
        """Regular files present in the sparse checkout, named by their index entry.

        The index is what tells a file from a symlink - with `core.symlinks=false`
        git writes a link as a plain file holding its target, which on disk looks
        like any other document - so the mode comes from `ls-files --stage` and
        only the working tree says which entries the patterns checked out.
        """
        root = self.listing_root(parsed.model_dump())
        prefix = f"{parsed.path_prefix}/" if parsed.path_prefix else ""
        files: list[RemoteFile] = []
        for entry in staged.split("\0"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            mode = meta.split(" ", 1)[0]
            if mode not in _FILE_MODES or not path.startswith(prefix):
                continue
            on_disk = checkout / path
            if not on_disk.is_file() or on_disk.is_symlink():
                continue
            files.append(
                RemoteFile(
                    id=path,
                    name=PurePosixPath(path).name,
                    size=on_disk.stat().st_size,
                    source_path=f"{root}{path.removeprefix(prefix)}",
                )
            )
        return files

    async def _environment(
        self, parsed: GitConfig, credential: StorableSecret | None
    ) -> dict[str, str]:
        """Everything git is told, through the environment rather than argv.

        The token rides `http.extraHeader` in `GIT_CONFIG_*`, so it is in no
        process listing and in no URL git could quote back in an error. Nothing
        from the worker's own git configuration is read (`GIT_CONFIG_GLOBAL`,
        `GIT_CONFIG_NOSYSTEM`), and `HOME` is not the worker's either.

        Raises:
            BadRequestError: no credential, or one that is not an API key.
            BadRequestError: the repository's host resolves inside the network.
        """
        if credential is None:
            raise BadRequestError(
                message=(
                    "This Git source has no credential. Add an access token to the Vault "
                    "as an API key and choose it as the source's credential."
                )
            )
        if not isinstance(credential, ApiKeySecret):
            raise BadRequestError(
                message="A Git source needs an API key, and the one it names is not one."
            )

        settings: list[tuple[str, str]] = [
            ("protocol.allow", "never"),
            ("protocol.https.allow", "always"),
            ("http.followRedirects", "false"),
            ("http.lowSpeedLimit", "1024"),
            ("http.lowSpeedTime", "60"),
            ("credential.helper", ""),
            ("core.symlinks", "false"),
            ("core.hooksPath", os.devnull),
            ("core.fsmonitor", "false"),
            ("transfer.bundleURI", "false"),
            ("submodule.recurse", "false"),
            ("advice.detachedHead", "false"),
        ]
        try:
            pinned = await asyncio.to_thread(
                resolve_pinned_url, parsed.repository_url, frozenset({"https"})
            )
        except UrlRefusedError as exc:
            # Our sentence, and it names the host rather than the URL, so it may
            # be stored - as a `ValueError` it would reach the sync log as a
            # class name.
            raise BadRequestError(message=str(exc)) from exc
        settings.append(("http.curloptResolve", _curl_resolve(pinned)))
        token = credential.api_key.get_secret_value()
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        settings.append(("http.extraHeader", f"Authorization: Basic {basic}"))

        env = {
            name: os.environ[name]
            for name in (
                "PATH",
                "HTTPS_PROXY",
                "https_proxy",
                "NO_PROXY",
                "no_proxy",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
                "GIT_SSL_CAINFO",
            )
            if name in os.environ
        }
        env.update(
            {
                "HOME": tempfile.gettempdir(),
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_COUNT": str(len(settings)),
            }
        )
        for index, (key, value) in enumerate(settings):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        return env

    async def _git(
        self,
        *args: str,
        env: dict[str, str],
        timeout: float,
        cwd: Path | None = None,
        stdin: str | None = None,
    ) -> str:
        """Run one git command and answer its stdout, or raise a sentence of ours.

        git's stderr is logged and never raised: it quotes the URL it failed on,
        and what reaches a sync log goes through `failure_summary`, which keeps an
        `AppException`'s message whole. The process is killed on a timeout and on
        cancellation - it must not outlive the sync that started it.

        Raises:
            BadRequestError: the token was refused, or the repository or branch
                does not exist for it.
            ExternalServiceError: anything else git gave up on, and a timeout.
            ConfigurationError: the worker has no git binary.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ConfigurationError(
                message="git is not installed on this worker, so a Git source cannot sync."
            ) from exc
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin is not None else None), timeout=timeout
            )
        except TimeoutError:
            await _reap(proc)
            raise ExternalServiceError(
                message=f"The repository did not answer within {timeout:g} seconds."
            ) from None
        except asyncio.CancelledError:
            await _reap(proc)
            raise
        if proc.returncode == 0:
            return out.decode("utf-8", "replace")

        stderr = err.decode("utf-8", "replace").strip()
        logger.warning("git %s failed (%s): %s", args[0], proc.returncode, stderr[:2000])
        lowered = stderr.lower()
        if any(marker in lowered for marker in _AUTH_FAILURES):
            raise BadRequestError(
                message=(
                    "The repository refused the source's token. Check that it has not "
                    "expired and that it can read this repository."
                )
            )
        if "remote branch" in lowered and "not found" in lowered:
            raise BadRequestError(message="The repository has no branch by that name.")
        if any(marker in lowered for marker in _NOT_FOUND):
            raise BadRequestError(
                message="The repository was not found, or the source's token cannot see it."
            )
        raise ExternalServiceError(message=f"git {args[0]} could not read the repository.")


def _make_workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="git-sync-"))


def _curl_resolve(pinned: PinnedAddress) -> str:
    """`host:port:addr[,addr]`, the `CURLOPT_RESOLVE` entry that pins every approved address."""
    addresses = ",".join(f"[{ip}]" if ":" in ip else ip for ip in pinned.ips)
    return f"{pinned.hostname}:{pinned.port}:{addresses}"


async def _reap(proc: asyncio.subprocess.Process) -> None:
    """Kill a git that has to stop, and wait for it so it is not left a zombie."""
    if proc.returncode is None:
        proc.kill()
    await asyncio.shield(proc.wait())
