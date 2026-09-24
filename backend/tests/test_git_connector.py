"""The Git sync connector, against a real repository and a real `git` (#987).

A stand-in for git would be a test of the stand-in: what matters here is what the
binary actually does with a sparse partial clone, a symlink in the tree and a
branch that is not there. So each test builds a repository on disk and the
connector clones it for real.

The one thing substituted is the transport. The connector permits HTTPS and
nothing else, so a test adds two settings on top of the ones it chose -
`url.<file-url>.insteadOf` for the HTTPS URL the config names, and permission for
the `file` transport that rewrite lands on - and pins the host to a public
address the rewrite never dials. Everything else in the environment is the
connector's own.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from app.core.exceptions import (
    AppException,
    BadRequestError,
    ConfigurationError,
    ExternalServiceError,
)
from app.core.sanitize import PinnedAddress, SSRFBlockedError
from app.core.secret_kinds import ApiKeySecret, GitTokenSecret
from app.services.rag.connectors import RemoteFile
from app.services.rag.connectors import git as git_module
from app.services.rag.connectors.git import GitConfig, GitConnector

pytestmark = pytest.mark.anyio

URL = "https://git.test/acme/handbook.git"
TOKEN = "github_pat_secret_value"
PINNED = PinnedAddress(hostname="git.test", port=443, ips=("93.184.216.34",))


# Resolved rather than named: a partial path in a subprocess call is a finding
# of its own (ruff S607).
GIT = shutil.which("git") or "/usr/bin/git"


def _run(*args: str, cwd: Path) -> str:
    """The fixture's own git, reading none of the developer's configuration."""
    return subprocess.run(
        [GIT, *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "PATH": os.environ["PATH"],
        },
    ).stdout


def _commit(repo: Path, message: str) -> None:
    _run("add", "-A", cwd=repo)
    _run("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", message, cwd=repo)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Documentation beside code, and a symlink that names a file outside the tree."""
    root = tmp_path / "origin"
    (root / "docs" / "guides").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "README.md").write_text("# Handbook\n")
    (root / "docs" / "intro.md").write_text("Welcome.\n")
    (root / "docs" / "guides" / "setup.md").write_text("Install it.\n")
    (root / "docs" / "notes.txt").write_text("Plain text.\n")
    (root / "app" / "main.py").write_text("print('not documentation')\n")
    (root / "docs" / "passwd.md").symlink_to("/etc/passwd")
    _run("init", "-q", "-b", "main", ".", cwd=root)
    _run("config", "uploadpack.allowFilter", "true", cwd=root)
    _commit(root, "initial")
    return root


@pytest.fixture
def local_transport(repo: Path) -> Iterator[None]:
    """Serve `URL` from `repo` over `file://`, on top of the connector's own settings."""
    real = GitConnector._environment

    async def environment(self: GitConnector, parsed: GitConfig, credential: Any) -> dict[str, str]:
        env = await real(self, parsed, credential)
        count = int(env["GIT_CONFIG_COUNT"])
        extra = [(f"url.{repo.as_uri()}.insteadOf", URL), ("protocol.file.allow", "always")]
        for offset, (key, value) in enumerate(extra):
            env[f"GIT_CONFIG_KEY_{count + offset}"] = key
            env[f"GIT_CONFIG_VALUE_{count + offset}"] = value
        env["GIT_CONFIG_COUNT"] = str(count + len(extra))
        return env

    with (
        patch.object(GitConnector, "_environment", environment),
        patch.object(git_module, "resolve_pinned_url", return_value=PINNED),
    ):
        yield


def _token(host: str = "git.test") -> GitTokenSecret:
    return GitTokenSecret(token=SecretStr(TOKEN), host=host)


def _config(**overrides: object) -> dict[str, object]:
    return {"repository_url": URL, **overrides}


@pytest.mark.usefixtures("local_transport")
class TestWhatASyncReads:
    async def test_the_default_patterns_list_documentation_and_not_code(self) -> None:
        connector = GitConnector()
        try:
            files = await connector.list_files(_config(), _token())
        finally:
            await connector.aclose()

        assert sorted(f.id for f in files) == [
            "README.md",
            "docs/guides/setup.md",
            "docs/intro.md",
            "docs/notes.txt",
        ]

    async def test_a_symlink_in_the_tree_is_not_a_document(self) -> None:
        """git writes it as a plain file holding `/etc/passwd`; the index says what it is."""
        connector = GitConnector()
        try:
            files = await connector.list_files(_config(), _token())
        finally:
            await connector.aclose()

        assert "docs/passwd.md" not in {f.id for f in files}

    async def test_a_path_prefix_narrows_the_listing_and_roots_the_source_path(self) -> None:
        connector = GitConnector()
        try:
            files = await connector.list_files(
                _config(path_prefix="/docs/", include=["*.md"]), _token()
            )
        finally:
            await connector.aclose()

        assert {f.id: f.source_path for f in files} == {
            "docs/intro.md": "git://git.test/acme/handbook@main/docs/intro.md",
        }

    async def test_the_code_the_patterns_leave_out_is_never_downloaded(self, repo: Path) -> None:
        """The cost claim, checked: a partial sparse clone holds no blob it did not check out."""
        code_blob = _run("rev-parse", "HEAD:app/main.py", cwd=repo).strip()
        connector = GitConnector()
        try:
            await connector.list_files(_config(), _token())
            assert connector._checkout is not None
            missing = _run(
                "rev-list", "--objects", "--missing=print", "HEAD", cwd=connector._checkout
            )
        finally:
            await connector.aclose()

        assert f"?{code_blob}" in missing.split()

    async def test_a_listed_file_downloads_its_bytes(self, tmp_path: Path) -> None:
        dest = tmp_path / "sync"
        dest.mkdir()
        connector = GitConnector()
        try:
            files = await connector.list_files(_config(include=["docs/guides/*.md"]), _token())
            landed = await connector.download_file(files[0], dest)
        finally:
            await connector.aclose()

        assert landed.read_text() == "Install it.\n"

    async def test_a_file_named_outside_the_checkout_is_refused(self, tmp_path: Path) -> None:
        connector = GitConnector()
        try:
            await connector.list_files(_config(), _token())
            with pytest.raises(BadRequestError):
                await connector.download_file(
                    RemoteFile(id="../../outside.md", name="outside.md", source_path="git://x/y"),
                    tmp_path,
                )
        finally:
            await connector.aclose()

    async def test_a_file_over_the_document_cap_is_refused_before_anything_is_written(
        self, repo: Path
    ) -> None:
        """Codex Security on #1867: 2 MiB of zeros is a few kilobytes on the wire,
        and a checkout used to write it whole before any size was looked at."""
        (repo / "docs" / "bomb.md").write_bytes(b"\0" * (2 * 1024 * 1024))
        _commit(repo, "bomb")
        connector = GitConnector()
        try:
            with (
                patch.object(git_module.settings, "MAX_UPLOAD_SIZE_MB", 1),
                pytest.raises(BadRequestError, match=r"docs/bomb\.md is 2 MB") as caught,
            ):
                await connector.list_files(_config(), _token())
            assert connector._workdir is not None
            written = [p.name for p in (connector._workdir / "repo").iterdir() if p.name != ".git"]
        finally:
            await connector.aclose()

        assert written == []
        assert caught.value.details["limit_bytes"] == 1024 * 1024

    @pytest.mark.parametrize(("limit", "refused"), [(54, True), (55, False)])
    async def test_the_whole_checkout_is_bounded_links_included(
        self, limit: int, refused: bool
    ) -> None:
        """The four documents are 44 bytes; the link beside them is written as an
        11-byte file holding its target, and a target can be any size."""
        connector = GitConnector()
        try:
            with patch.object(git_module, "MAX_CHECKOUT_BYTES", limit):
                if refused:
                    with pytest.raises(BadRequestError, match="one sync may check out"):
                        await connector.list_files(_config(), _token())
                else:
                    assert len(await connector.list_files(_config(), _token())) == 4
        finally:
            await connector.aclose()

    async def test_patterns_matching_nothing_list_nothing(self) -> None:
        connector = GitConnector()
        try:
            files = await connector.list_files(_config(include=["handbook/*.md"]), _token())
        finally:
            await connector.aclose()

        assert files == []

    async def test_the_clone_is_removed_when_the_sync_is_over(self) -> None:
        connector = GitConnector()
        await connector.list_files(_config(), _token())
        workdir = connector._workdir
        assert workdir is not None and workdir.exists()

        await connector.aclose()
        await connector.aclose()

        assert not workdir.exists()


@pytest.mark.usefixtures("local_transport")
class TestTheChangeSignal:
    async def test_the_version_is_the_branch_head_and_moves_with_a_commit(self, repo: Path) -> None:
        before = await GitConnector().remote_version(_config(), _token())
        assert before == _run("rev-parse", "HEAD", cwd=repo).strip()

        (repo / "docs" / "intro.md").write_text("Welcome, again.\n")
        _commit(repo, "edit")

        assert await GitConnector().remote_version(_config(), _token()) != before

    async def test_a_branch_the_repository_does_not_have_is_refused_by_name(self) -> None:
        with pytest.raises(BadRequestError, match="no branch named 'release'"):
            await GitConnector().remote_version(_config(branch="release"), _token())

    async def test_cloning_a_missing_branch_is_our_sentence_and_not_gits(self) -> None:
        connector = GitConnector()
        try:
            with pytest.raises(BadRequestError, match="no branch by that name"):
                await connector.list_files(_config(branch="release"), _token())
        finally:
            await connector.aclose()

    def test_the_source_root_names_repository_branch_and_prefix(self) -> None:
        def root(**overrides: object) -> str:
            return GitConnector.source_root(GitConfig.model_validate(_config(**overrides)))

        assert root() == "git://git.test/acme/handbook@main/"
        assert root(branch="v2", path_prefix="docs") == "git://git.test/acme/handbook@v2/docs/"

    def test_two_servers_on_one_host_are_two_repositories(self) -> None:
        """Codex on #1867: the port used to be dropped, so two servers' documents
        in one collection shared addresses."""

        def root(url: str) -> str:
            return GitConnector.source_root(GitConfig.model_validate(_config(repository_url=url)))

        assert (
            root("https://git.test:8443/acme/handbook.git")
            == "git://git.test:8443/acme/handbook@main/"
        )
        assert (
            root("https://git.test:9443/acme/handbook.git")
            == "git://git.test:9443/acme/handbook@main/"
        )
        assert root("https://git.test:443/acme/handbook.git") == root(URL)
        assert root("https://[2606:4700::1]:8443/a/b.git") == "git://[2606:4700::1]:8443/a/b@main/"

    def test_a_git_source_deletes_what_it_no_longer_lists(self) -> None:
        assert GitConnector.REMOVES_UNLISTED is True


class TestWhatGitIsTold:
    async def test_the_token_rides_a_header_in_the_environment_and_never_the_url(self) -> None:
        with patch.object(git_module, "resolve_pinned_url", return_value=PINNED):
            env = await GitConnector()._environment(GitConfig.model_validate(_config()), _token())

        settings = {
            env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
            for i in range(int(env["GIT_CONFIG_COUNT"]))
        }
        basic = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
        assert settings["http.extraHeader"] == f"Authorization: Basic {basic}"
        assert settings["protocol.allow"] == "never"
        assert settings["protocol.https.allow"] == "always"
        assert settings["http.followRedirects"] == "false"
        assert settings["http.curloptResolve"] == "git.test:443:93.184.216.34"
        assert settings["core.symlinks"] == "false"
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_CONFIG_GLOBAL"] != str(Path.home() / ".gitconfig")
        assert TOKEN not in " ".join(k for k in env if not k.startswith("GIT_CONFIG_VALUE_"))

    async def test_a_literal_address_is_not_given_a_resolve_entry(self) -> None:
        """`CURLOPT_RESOLVE` cannot name an IPv6 host, and a literal is pinned already."""
        url = "https://[2606:4700::1111]/acme/handbook.git"
        pinned = PinnedAddress(hostname="2606:4700::1111", port=443, ips=("2606:4700::1111",))
        with patch.object(git_module, "resolve_pinned_url", return_value=pinned):
            env = await GitConnector()._environment(
                GitConfig.model_validate(_config(repository_url=url)),
                _token(host="[2606:4700::1111]"),
            )

        keys = {env[f"GIT_CONFIG_KEY_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))}
        assert "http.curloptResolve" not in keys

    def test_an_ipv6_address_is_bracketed_for_curl(self) -> None:
        pinned = PinnedAddress(hostname="git.test", port=443, ips=("2606:4700::1", "93.184.216.34"))

        assert git_module._curl_resolve(pinned) == "git.test:443:[2606:4700::1],93.184.216.34"

    async def test_a_host_inside_the_network_is_refused_at_sync_time(self) -> None:
        refused = SSRFBlockedError("git.internal resolves to a private address")
        with (
            patch.object(git_module, "resolve_pinned_url", side_effect=refused),
            pytest.raises(BadRequestError, match="private address"),
        ):
            await GitConnector().remote_version(_config(), _token())

    async def test_a_source_with_no_credential_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="no credential"):
            await GitConnector().remote_version(_config(), None)

    async def test_an_api_key_is_not_a_git_token(self) -> None:
        """Any API key used to be eligible - the organization's model key included -
        and the URL is the editor's to choose, so the key went wherever they pointed
        it. A Git source now takes only a token that names its own host."""
        model_key = ApiKeySecret(api_key=SecretStr("sk-model-provider-key"))
        with pytest.raises(BadRequestError, match="needs a Git access token"):
            await GitConnector().remote_version(_config(), model_key)

    async def test_a_token_is_never_sent_to_a_host_it_was_not_added_for(self) -> None:
        spawned: list[object] = []

        async def spawn(*args: object, **_: object) -> None:
            spawned.append(args)

        with (
            patch.object(git_module, "resolve_pinned_url", return_value=PINNED),
            patch.object(git_module.asyncio, "create_subprocess_exec", new=spawn),
            pytest.raises(BadRequestError, match=r"added for github\.com") as caught,
        ):
            await GitConnector().remote_version(_config(), _token(host="github.com"))

        assert spawned == []
        assert TOKEN not in caught.value.message

    @pytest.mark.parametrize(
        ("host", "url", "allowed"),
        [
            ("GitHub.com", "https://github.com/a/b.git", True),
            ("github.com:443", "https://github.com/a/b.git", True),
            ("git.example.com:8443", "https://git.example.com:8443/a/b.git", True),
            ("git.example.com", "https://git.example.com:8443/a/b.git", False),
            ("github.com", "https://github.com.evil.test/a/b.git", False),
            ("[2606:4700::1]", "https://[2606:4700::1]/a/b.git", True),
        ],
    )
    def test_the_host_is_matched_exactly_with_its_port(
        self, host: str, url: str, allowed: bool
    ) -> None:
        parts = git_module.urlsplit(url)

        assert _token(host=host).allows(parts.hostname or "", parts.port) is allowed

    async def test_an_internationalized_host_is_matched_and_pinned_in_its_encoded_form(
        self,
    ) -> None:
        """Codex on #1867: the vault stores `xn--bcher-kva.example`, the URL said
        `bücher.example`, and every sync refused the token. The pin must name the
        encoded host too, since that is the name curl looks up."""
        pinned = PinnedAddress(hostname="xn--bcher-kva.example", port=443, ips=("93.184.216.34",))
        parsed = GitConfig.model_validate(
            _config(repository_url="https://Bücher.example/acme/docs.git")
        )
        with patch.object(git_module, "resolve_pinned_url", return_value=pinned) as resolve:
            env = await GitConnector()._environment(parsed, _token(host="xn--bcher-kva.example"))

        assert parsed.repository_url == "https://xn--bcher-kva.example/acme/docs.git"
        assert resolve.call_args.args[0] == parsed.repository_url
        assert "xn--bcher-kva.example:443:93.184.216.34" in env.values()
        assert GitConnector.source_root(parsed) == "git://xn--bcher-kva.example/acme/docs@main/"

    def test_an_encoded_host_keeps_its_port(self) -> None:
        parsed = GitConfig.model_validate(
            _config(repository_url="https://bücher.example:8443/a/b.git")
        )

        assert parsed.repository_url == "https://xn--bcher-kva.example:8443/a/b.git"

    def test_the_vault_hint_is_the_tokens_last_four_and_not_the_host(self) -> None:
        assert _token().hint == TOKEN[-4:]


class _Process:
    """A git that says what it is told to, or never answers."""

    pid = 424242

    def __init__(self, *, returncode: int = 0, stderr: bytes = b"", hang: bool = False) -> None:
        self.returncode: int | None = None if hang else returncode
        self._stderr = stderr
        self._hang = hang

    async def communicate(self, _input: bytes | None = None) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(3600)
        return b"", self._stderr

    async def wait(self) -> int:
        return self.returncode or 0


class TestWhatAFailureSays:
    killed: list[int]

    async def _fail_with(self, process: _Process, *, timeout: float = 5.0) -> AppException:
        async def spawn(*_: object, **__: object) -> _Process:
            return process

        self.killed = []
        with (
            patch.object(git_module.asyncio, "create_subprocess_exec", new=spawn),
            patch.object(git_module.os, "killpg", new=lambda pgid, _sig: self.killed.append(pgid)),
            pytest.raises(AppException) as caught,
        ):
            await GitConnector()._git("ls-remote", env={}, timeout=timeout)
        return caught.value

    @pytest.mark.parametrize(
        "stderr",
        [
            b"remote: Invalid username or password.\nfatal: Authentication failed for 'https://github.com/acme/x/'",
            b"fatal: unable to access 'https://gitlab.com/acme/x.git/': The requested URL returned error: 403",
        ],
    )
    async def test_a_refused_token_is_named_as_the_token(self, stderr: bytes) -> None:
        refusal = await self._fail_with(_Process(returncode=128, stderr=stderr))

        assert isinstance(refusal, BadRequestError)
        assert "token" in refusal.message
        assert "https://" not in refusal.message

    async def test_a_repository_that_is_not_there_says_so_without_the_url(self) -> None:
        stderr = b"remote: Repository not found.\nfatal: repository 'https://github.com/acme/x/' not found"
        refusal = await self._fail_with(_Process(returncode=128, stderr=stderr))

        assert isinstance(refusal, BadRequestError)
        assert "not found" in refusal.message
        assert "github.com" not in refusal.message

    async def test_anything_else_is_the_upstream_and_names_no_url(self) -> None:
        stderr = b"fatal: unable to access 'https://git.test/x/': Could not resolve host: git.test"
        refusal = await self._fail_with(_Process(returncode=128, stderr=stderr))

        assert isinstance(refusal, ExternalServiceError)
        assert "git.test" not in refusal.message

    async def test_a_git_that_stalls_is_killed_at_the_timeout(self) -> None:
        process = _Process(hang=True)
        refusal = await self._fail_with(process, timeout=0.05)

        assert isinstance(refusal, ExternalServiceError)
        assert self.killed == [_Process.pid]

    async def test_a_timeout_kills_the_helpers_git_started_as_well(self, tmp_path: Path) -> None:
        """A real process tree: an alias that starts a child, as `clone` starts
        `git-remote-https`. Killing only the leader left the child running with the
        environment that carries the token."""
        pidfile = tmp_path / "child.pid"
        env = {
            "PATH": os.environ["PATH"],
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "alias.stall",
            "GIT_CONFIG_VALUE_0": f"!sleep 60 & echo $! > {pidfile}; wait",
        }

        with pytest.raises(ExternalServiceError):
            await GitConnector()._git("stall", env=env, timeout=1.0, cwd=tmp_path)

        child = int(pidfile.read_text())
        assert await asyncio.to_thread(_gone_within, child, 5.0)

    async def test_a_worker_without_git_is_a_configuration_problem(self) -> None:
        async def missing(*_: object, **__: object) -> _Process:
            raise FileNotFoundError("git")

        with (
            patch.object(git_module.asyncio, "create_subprocess_exec", new=missing),
            pytest.raises(ConfigurationError, match="git is not installed"),
        ):
            await GitConnector()._git("ls-remote", env={}, timeout=1.0)


def _gone_within(pid: int, seconds: float) -> bool:
    """Whether `pid` stops existing within `seconds` - a SIGKILL is not instant."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


class TestWhatTheFormAccepts:
    @staticmethod
    async def _refusal(config: dict[str, object]) -> tuple[str | None, str] | None:
        with patch.object(git_module, "resolve_pinned_url", return_value=PINNED):
            refusal = await GitConnector().validate_config(config)
        return None if refusal is None else (refusal.field, refusal.message)

    async def test_a_public_https_clone_url_is_accepted_with_the_defaults(self) -> None:
        assert await self._refusal(_config()) is None

    async def test_the_default_patterns_are_documentation(self) -> None:
        assert GitConfig.model_validate(_config()).include == ["**/*.md", "**/*.txt"]

    @pytest.mark.parametrize(
        ("config", "field"),
        [
            ({}, "repository_url"),
            ({"repository_url": "http://github.com/acme/x.git"}, "repository_url"),
            ({"repository_url": "git@github.com:acme/x.git"}, "repository_url"),
            ({"repository_url": f"https://{TOKEN}@github.com/acme/x.git"}, "repository_url"),
            ({"repository_url": "https://github.com/acme/x.git?ref=main"}, "repository_url"),
            ({"repository_url": "https://github.com/"}, "repository_url"),
            ({"repository_url": f"https://{'a' * 64}.example.com/x.git"}, "repository_url"),
            ({"repository_url": "https://github.com:99999/acme/x.git"}, "repository_url"),
            (_config(branch="--upload-pack=touch /tmp/x"), "branch"),
            (_config(branch="main..dev"), "branch"),
            (_config(path_prefix="../secrets"), "path_prefix"),
            (_config(path_prefix="-docs"), "path_prefix"),
            (_config(include=[]), "include"),
            (_config(include=["!secrets/**"]), "include"),
            (_config(include=["docs/*.md\n/app/**"]), "include"),
        ],
    )
    async def test_a_value_git_could_misread_is_refused_on_its_field(
        self, config: dict[str, object], field: str
    ) -> None:
        refusal = await self._refusal(config)

        assert refusal is not None
        assert refusal[0] == field
        assert TOKEN not in refusal[1]

    async def test_a_url_naming_an_internal_host_is_refused_on_the_form(self) -> None:
        refused = SSRFBlockedError("git.internal resolves to a private address")
        with patch.object(git_module, "resolve_pinned_url", side_effect=refused):
            refusal = await GitConnector().validate_config(
                {"repository_url": "https://git.internal/acme/x.git"}
            )

        assert refusal is not None
        assert refusal.field == "repository_url"

    def test_a_prefix_is_normalized_to_the_way_the_index_spells_it(self) -> None:
        assert (
            GitConfig.model_validate(_config(path_prefix="./docs//guides/")).path_prefix
            == "docs/guides"
        )
