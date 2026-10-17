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
from app.agents.capabilities.mirage import Mirage, MirageConfig
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


class TestTheConfiguration:
    def test_repositories_are_trimmed_and_parsed_with_their_branch(self) -> None:
        config = MirageConfig(repositories=[" acme/api ", "acme/web@release/1.0", " "])
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
            MirageConfig(repositories=repositories)


class TestBuildingIt:
    def _build(self, secret: object, **config: object) -> Any:
        binding = CapabilityBinding(
            capability_id="mirage",
            config={"repositories": ["acme/api", "acme/web@main"], **config},
            secret_id=None,
        )
        definition = _registry.get("mirage")
        context = _registry.CapabilityBuildContext(
            binding=binding,
            config=definition.validate_config(binding.config),
            secret=secret,  # type: ignore[arg-type]
        )
        return definition.builder(context)

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
        assert "/scratch/" not in without
