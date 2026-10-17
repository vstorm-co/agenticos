"""The Mirage virtual terminal: what it mounts, what it lets a command do, and when.

Every repository here is a RAM resource standing in for GitHub, seeded with a
file or two, so the tests read the real Mirage shell and its real refusals with
no network. What matters is the split the capability is built on: the explore
tool's view refuses every write by construction, the run tool may write into
the scratch folder and nowhere else, and the token reaches neither the model
nor the configuration.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from mirage import MountMode, Workspace
from mirage.resource.ram.ram import RAMResource
from pydantic import SecretStr, ValidationError

from app.agents.capabilities import _registry
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.mirage import (
    MIRAGE_TREES_RESOURCE,
    Mirage,
    MirageConfig,
    MountedTree,
    TreeFile,
    TreeUnavailable,
)
from app.agents.capabilities.mirage import _capability as capability_module
from app.agents.capabilities.mirage._capability import GitHubMount
from app.agents.capabilities.mirage._toolset import Terminal
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret, GitTokenSecret

pytestmark = pytest.mark.anyio

TOKEN = "ghp_live_do_not_print"


async def _seeded(files: dict[str, str]) -> RAMResource:
    """A RAM tree holding these files, written through Mirage's own shell."""
    resource = RAMResource()
    workspace = Workspace({"/": (resource, MountMode.WRITE)}, mode=MountMode.WRITE)
    for path, text in files.items():
        await workspace.execute(f"echo '{text}' > /{path}")
    await workspace.close()
    return resource


@pytest.fixture
async def built(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str, str | None]]:
    """Each repository a seeded RAM tree in place of GitHub; what was asked for, in order."""
    trees = {
        "acme/api": await _seeded({"README.md": "TODO: document the API", "main.py": "print(1)"}),
        "acme/web": await _seeded({"README.md": "TODO: ship the site"}),
    }
    asked: list[tuple[str, str, str, str | None]] = []

    def fake(config: Any, *, owner: str, repo: str, ref: str | None) -> RAMResource:
        asked.append((config.token.get_secret_value(), owner, repo, ref))
        return trees[f"{owner}/{repo}"]

    monkeypatch.setattr(capability_module, "GitHubResource", fake)
    return asked


def _terminal(**overrides: Any) -> Mirage[Any]:
    values: dict[str, Any] = {
        "repositories": (GitHubMount("acme", "api"), GitHubMount("acme", "web", ref="main")),
        "token": TOKEN,
    }
    return Mirage(**{**values, **overrides})


def _tools(capability: Mirage[Any]) -> tuple[Any, Any]:
    tools = capability.get_toolset().tools  # type: ignore[union-attr]
    return tools["mirage_explore"].function, tools["mirage_run"].function


def _call_ctx() -> MagicMock:
    return MagicMock(retry=0, max_retries=1, retries={})


def _tree(path: str, files: dict[str, str], **overrides: Any) -> MountedTree:
    """A folder over these files, as the runner would hand one over."""
    closed: list[str] = overrides.pop("closed", [])

    async def list_files() -> list[TreeFile]:
        return [TreeFile(path=name, size=len(text)) for name, text in files.items()]

    async def read_file(name: str) -> bytes:
        return files[name].encode()

    async def close() -> None:
        closed.append(path)

    values: dict[str, Any] = {
        "path": path,
        "describe": f"the files of {path}",
        "list_files": list_files,
        "read_file": read_file,
        "close": close,
    }
    return MountedTree(**{**values, **overrides})


class TestTheConfiguration:
    def test_repositories_are_trimmed_and_parsed_with_their_branch(self) -> None:
        config = MirageConfig(github=True, repositories=[" acme/api ", "acme/web@release/1.0", " "])
        assert config.repositories == ["acme/api", "acme/web@release/1.0"]

    @pytest.mark.parametrize(
        "repositories",
        [
            [],
            ["acme"],
            ["acme/api/../secrets"],
            ["https://github.com/acme/api"],
            ["a/b", "A/B@dev"],
        ],
    )
    def test_a_repository_that_is_not_one_is_refused(self, repositories: list[str]) -> None:
        with pytest.raises(ValidationError):
            MirageConfig(github=True, repositories=repositories)

    def test_the_default_mounts_the_knowledge_bases(self) -> None:
        config = MirageConfig()
        assert config.knowledge is True and config.github is False

    @pytest.mark.parametrize(
        ("config", "message"),
        [
            ({"knowledge": False}, "Mount at least one source"),
            ({"repositories": ["acme/api"]}, "Turn GitHub repositories on"),
            ({"allowed_commands": ["ls; rm -rf /"]}, "is not a command name"),
            ({"hidden_paths": ["docs/secret"]}, "is not an absolute path"),
            ({"hidden_paths": ["/knowledge/../sources"]}, "is not an absolute path"),
        ],
    )
    def test_a_policy_or_mount_set_that_says_nothing_true_is_refused(
        self, config: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValidationError, match=message):
            MirageConfig(**config)

    def test_policy_entries_are_trimmed(self) -> None:
        config = MirageConfig(
            allowed_commands=[" ls ", "git log", " "], hidden_paths=["*.env", " /sources/hr "]
        )
        assert config.allowed_commands == ["ls", "git log"]
        assert config.hidden_paths == ["*.env", "/sources/hr"]


class TestBuildingIt:
    def _build(
        self, secret: object, resources: dict[str, Any] | None = None, **config: object
    ) -> Any:
        binding = CapabilityBinding(
            capability_id="mirage",
            config={"github": True, "repositories": ["acme/api", "acme/web@main"], **config},
            secret_id=None,
        )
        definition = _registry.get("mirage")
        context = _registry.CapabilityBuildContext(
            binding=binding,
            config=definition.validate_config(binding.config),
            resources=resources or {},
            secret=secret,  # type: ignore[arg-type]
        )
        return definition.builder(context)

    def test_without_github_it_needs_no_token_and_mounts_the_runners_folders(self) -> None:
        folder = _tree("/knowledge/handbook/", {"a.md": "x"})
        built = self._build(
            None,
            {MIRAGE_TREES_RESOURCE: (folder,)},
            github=False,
            repositories=[],
            allowed_commands=["ls"],
            hidden_paths=["*.env"],
        )
        assert built.repositories == () and built.token == ""
        assert built.trees == (folder,)
        assert built.allowed_commands == ("ls",) and built.hidden_paths == ("*.env",)

    def test_the_token_is_asked_for_only_when_github_is_on(self) -> None:
        definition = _registry.get("mirage")
        assert definition.needs_secret(MirageConfig(github=True, repositories=["a/b"]))
        assert not definition.needs_secret(MirageConfig())

    def test_it_mounts_each_repository_with_the_token_from_the_vault(self) -> None:
        built = self._build(
            GitTokenSecret(token=SecretStr(TOKEN), host="github.com"), scratch=False
        )
        assert built.repositories == (
            GitHubMount("acme", "api"),
            GitHubMount("acme", "web", "main"),
        )
        assert built.scratch is False
        assert TOKEN not in repr(built)

    def test_a_token_sealed_for_another_host_is_never_sent_to_github(self) -> None:
        with pytest.raises(BadRequestError, match=r"not sealed for github\.com"):
            self._build(GitTokenSecret(token=SecretStr(TOKEN), host="gitlab.example.com"))

    @pytest.mark.parametrize("secret", [None, ApiKeySecret(api_key="sk-live-12345678")])
    def test_without_a_git_token_it_does_not_build(self, secret: object) -> None:
        with pytest.raises(BadRequestError, match="needs a GitHub token"):
            self._build(secret)


class TestWhatACommandMayDo:
    async def test_explore_lists_and_greps_across_both_repositories(
        self, built: list[tuple[str, str, str, str | None]]
    ) -> None:
        run = await _terminal().for_run(MagicMock())
        explore, _ = _tools(run)

        listing = await explore(_call_ctx(), "ls /github/acme")
        found = await explore(_call_ctx(), "grep -rl TODO /github")

        assert listing.startswith("exit code: 0") and "api" in listing and "web" in listing
        assert "/github/acme/api/README.md" in found and "/github/acme/web/README.md" in found
        assert built == [(TOKEN, "acme", "api", None), (TOKEN, "acme", "web", "main")]

    @pytest.mark.usefixtures("built")
    async def test_writes_land_in_scratch_only_and_explore_refuses_them_all(self) -> None:
        run = await _terminal().for_run(MagicMock())
        explore, write = _tools(run)

        written = await write(_call_ctx(), "grep -rl TODO /github > /scratch/todo.txt")
        read_back = await explore(_call_ctx(), "cat /scratch/todo.txt")
        into_repo = await write(_call_ctx(), "echo x > /github/acme/api/hack.py")
        from_explore = await explore(_call_ctx(), "echo x > /scratch/other.txt")

        assert written.startswith("exit code: 0")
        assert "acme/web/README.md" in read_back
        assert into_repo.startswith("exit code: 1") and "[stderr]" in into_repo
        assert from_explore.startswith("exit code: 1") and "Read-only" in from_explore

    async def test_an_empty_command_is_sent_back(self) -> None:
        explore, write = _tools(await _terminal().for_run(MagicMock()))
        assert "Pass a shell command" in await explore(_call_ctx(), "  ")
        assert "Pass a shell command" in await write(_call_ctx(), "")


class TestTheLimits:
    def _terminal_over(self, result: Any) -> Terminal:
        workspace = MagicMock(execute=result)
        views = MagicMock(explore=workspace, run=workspace)
        return Terminal(open_views=lambda: views, timeout_seconds=1, max_output_chars=1_000)

    async def test_a_command_past_its_timeout_is_stopped(self) -> None:
        async def forever(_command: str) -> None:
            await asyncio.sleep(10)

        answer = await self._terminal_over(forever).run("grep -r x /", writable=False)
        assert answer.startswith("exit code: timeout")

    async def test_long_output_is_cut_and_says_where(self) -> None:
        async def flood(_command: str) -> Any:
            async def text() -> str:
                return "x" * 5_000

            return MagicMock(exit_code=0, stdout_str=text, stderr=None)

        answer = await self._terminal_over(flood).run("cat big", writable=True)
        assert "[output cut at 1000 characters" in answer
        assert len(answer) < 1_200


class TestOneRun:
    @pytest.mark.usefixtures("built")
    async def test_each_run_gets_its_own_terminal_and_closes_it(self) -> None:
        shared = _terminal(scratch=False)
        first = await shared.for_run(MagicMock())
        assert first is not shared

        explore, _ = _tools(first)
        await explore(_call_ctx(), "ls /")
        assert first._views is not None

        async def handler() -> str:
            return "answered"

        assert await first.wrap_run(MagicMock(), handler=handler) == "answered"
        assert first._views is None
        # A run that never touched the terminal has nothing to close.
        assert await (await shared.for_run(MagicMock())).wrap_run(MagicMock(), handler=handler)

    def test_the_instructions_name_each_mount_and_the_scratch_folder_only_when_on(self) -> None:
        with_scratch = _terminal().get_instructions()
        without = _terminal(scratch=False).get_instructions()
        assert "/github/acme/api/" in with_scratch and "/scratch/" in with_scratch
        assert "mirage_run" in with_scratch
        assert "/scratch/" not in without and "mirage_run" not in without

    def test_the_instructions_name_each_folder_and_the_commands_that_exist(self) -> None:
        text = Mirage(
            trees=(_tree("/knowledge/handbook/", {}),), allowed_commands=("ls", "grep")
        ).get_instructions()
        assert "/knowledge/handbook/: the files of /knowledge/handbook/" in text
        assert "Only these commands exist: ls, grep." in text
        assert "Only these" not in Mirage(trees=()).get_instructions()

    async def test_a_runs_folders_are_closed_with_it(self) -> None:
        closed: list[str] = []
        run = await Mirage(
            trees=(
                _tree("/sources/a/", {}, closed=closed),
                _tree("/sources/b/", {}, closed=closed),
                # A folder that opened nothing has nothing to close.
                MountedTree(
                    path="/knowledge/kb/",
                    describe="kb",
                    list_files=_tree("/knowledge/kb/", {}).list_files,
                    read_file=_tree("/knowledge/kb/", {}).read_file,
                ),
            )
        ).for_run(MagicMock())

        async def handler() -> str:
            return "answered"

        assert await run.wrap_run(MagicMock(), handler=handler) == "answered"
        assert closed == ["/sources/a/", "/sources/b/"]


class TestFoldersFromThePlatform:
    """Knowledge bases and sync sources, mounted through `tree_resource`."""

    def _two_sources(self) -> Mirage[Any]:
        return Mirage(
            trees=(
                _tree(
                    "/knowledge/handbook/",
                    {"hr/leave.md": "Holidays: 26 days", "contracts/nda.md": "Notice: 30 days"},
                ),
                _tree("/sources/bucket/", {"reports/q3.txt": "Revenue up 12 days late"}),
            )
        )

    async def test_it_lists_and_greps_across_two_mounted_sources(self) -> None:
        explore, _ = _tools(await self._two_sources().for_run(MagicMock()))

        root = await explore(_call_ctx(), "ls /knowledge/handbook")
        nested = await explore(_call_ctx(), "ls /knowledge/handbook/hr")
        found = await explore(_call_ctx(), "grep -rn days /")
        named = await explore(_call_ctx(), "find /sources -name '*.txt'")
        read = await explore(_call_ctx(), "cat /sources/bucket/reports/q3.txt")

        assert "contracts" in root and "hr" in root
        assert "leave.md" in nested
        assert "/knowledge/handbook/hr/leave.md:1:Holidays: 26 days" in found
        assert "/sources/bucket/reports/q3.txt:1:" in found
        assert "/sources/bucket/reports/q3.txt" in named
        assert "Revenue up" in read

    async def test_a_path_the_folder_does_not_hold_is_not_found(self) -> None:
        explore, _ = _tools(await self._two_sources().for_run(MagicMock()))
        assert "No such file" in await explore(_call_ctx(), "cat /knowledge/handbook/nope.md")
        assert "No such file" in await explore(_call_ctx(), "ls /knowledge/handbook/nope")

    async def test_nothing_is_written_into_a_folder_from_either_tool(self) -> None:
        explore, write = _tools(await self._two_sources().for_run(MagicMock()))
        from_run = await write(_call_ctx(), "echo x > /knowledge/handbook/new.md")
        from_explore = await explore(_call_ctx(), "echo x > /sources/bucket/new.txt")
        assert from_run.startswith("exit code: 1") and "Operation not supported" in from_run
        assert from_explore.startswith("exit code: 1")

    async def test_a_folder_is_listed_once_per_run(self) -> None:
        calls: list[str] = []

        async def list_files() -> list[TreeFile]:
            calls.append("listed")
            return [TreeFile(path="a.md")]

        explore, _ = _tools(
            await Mirage(
                trees=(_tree("/sources/s/", {"a.md": "x"}, list_files=list_files),)
            ).for_run(MagicMock())
        )
        await explore(_call_ctx(), "ls /sources/s")
        await explore(_call_ctx(), "cat /sources/s/a.md")
        assert calls == ["listed"]

    async def test_a_sources_own_error_never_reaches_the_model(self) -> None:
        async def leaky_list() -> list[TreeFile]:
            raise RuntimeError("AccessDenied for AKIASECRET123 on arn:aws:s3:::payroll")

        async def leaky_read(_path: str) -> bytes:
            raise RuntimeError("401 with token ghp_leak")

        explore, _ = _tools(
            await Mirage(
                trees=(
                    _tree("/sources/bad/", {}, list_files=leaky_list),
                    _tree("/sources/half/", {"a.md": "x"}, read_file=leaky_read),
                )
            ).for_run(MagicMock())
        )
        listed = await explore(_call_ctx(), "ls /sources/bad")
        read = await explore(_call_ctx(), "cat /sources/half/a.md")

        assert not listed.startswith("exit code: 0") and "AKIASECRET123" not in listed
        assert "ghp_leak" not in read and "/sources/half/ could not be read" in read

    async def test_a_refusal_the_platform_wrote_is_shown_as_written(self) -> None:
        async def too_big(_path: str) -> bytes:
            raise TreeUnavailable("a.md is larger than 20 MB and is not read here")

        explore, _ = _tools(
            await Mirage(trees=(_tree("/sources/s/", {"a.md": "x"}, read_file=too_big),)).for_run(
                MagicMock()
            )
        )
        assert "larger than 20 MB" in await explore(_call_ctx(), "cat /sources/s/a.md")


class TestThePolicy:
    """`allowed_commands` and `hidden_paths`, enforced by Mirage's own shell."""

    async def test_only_the_allowed_commands_exist_in_either_tool(self) -> None:
        run = await Mirage(
            trees=(_tree("/knowledge/kb/", {"a.md": "hello"}),), allowed_commands=("cat", "grep")
        ).for_run(MagicMock())
        explore, write = _tools(run)

        assert "hello" in await explore(_call_ctx(), "cat /knowledge/kb/a.md")
        refused = await explore(_call_ctx(), "ls /knowledge/kb")
        nested = await write(_call_ctx(), "cat /knowledge/kb/a.md | sort")
        assert "exit code: 127" in refused and "command not found" in refused
        assert "exit code: 127" in nested

    async def test_a_hidden_path_does_not_exist_for_the_agent(self) -> None:
        run = await Mirage(
            trees=(_tree("/knowledge/kb/", {"hr/pay.md": "salary 1", "faq.md": "salary 2"}),),
            hidden_paths=("/knowledge/kb/hr",),
        ).for_run(MagicMock())
        explore, _ = _tools(run)

        listing = await explore(_call_ctx(), "ls /knowledge/kb")
        found = await explore(_call_ctx(), "grep -rn salary /knowledge")
        read = await explore(_call_ctx(), "cat /knowledge/kb/hr/pay.md")

        assert "faq.md" in listing and "hr" not in listing
        assert "salary 2" in found and "salary 1" not in found
        assert "No such file" in read
