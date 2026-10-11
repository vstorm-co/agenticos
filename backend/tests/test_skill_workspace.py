"""Skills as files, and what comes back when an agent edits them.

Three properties matter more than the feature.

*A run is never broken by this.* Materialising is best-effort - a workspace past
its ceiling still runs the agent, with the skills in the prompt as before - and
collecting is best-effort too, because it happens in the same `finally` that
records what the run cost.

*A deletion is not a change.* A model that never touched a resource and one that
meant to delete it leave the same absence, and guessing wrong silently drops
organizational know-how.

*Nothing is proposed unless something actually differs.* Otherwise every turn of
every conversation would leave a reviewer another copy of the same skill.

Both entry points are awaited, and work in the run's workspace. The workspaces
below are a stored document, which is what a `state` agent works in; the
failures a container shows are wrappers around one.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import FileEntry, Workspace, WrapperWorkspace
from pydantic_ai_backends import StateBackend

from app.agents.capabilities.sandbox._capped import CappedStateBackend
from app.services.skill_workspace import (
    SKILLS_ROOT,
    collect_changes,
    materialise,
    render_body,
)
from tests.workspaces import document_workspace

pytestmark = pytest.mark.anyio


class _Resource:
    def __init__(self, name: str, content: str) -> None:
        self.name = name
        self.content = content


class _Skill:
    def __init__(
        self,
        name: str = "refunds",
        description: str = "How refunds work.",
        content: str = "Ask for the order id.",
        resources: list[_Resource] | None = None,
    ) -> None:
        self.id = uuid4()
        self.name = name
        self.description = description
        self.content = content
        self.resources = resources or []


def _document() -> tuple[StateBackend, Workspace]:
    document = StateBackend()
    return document, document_workspace(document)


def _write(document: StateBackend, path: str, text: str) -> None:
    document.write_bytes(path, text.encode())


class _WriteFails(WrapperWorkspace):
    async def write_bytes(self, path: str, data: bytes) -> None:
        raise RuntimeError("no")


class _Unmeasured(WrapperWorkspace):
    """A listing whose sizes are absent rather than zero."""

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        return [
            FileEntry(name=e.name, path=e.path, is_dir=e.is_dir, size=None)
            for e in await super().list_dir(path)
        ]


class _ListingFails(WrapperWorkspace):
    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        raise RuntimeError("the service is down")


class TestWritingSkillsIntoTheWorkspace:
    async def test_the_body_and_every_resource_land_beside_each_other(self):
        """Beside each other because that is the whole feature: a script the model
        could previously only quote is now a path its shell can run."""
        skill = _Skill(resources=[_Resource("reconcile.py", "print(1)")])
        document, workspace = _document()

        await materialise(workspace, [skill])

        body = document.read_bytes(f"{SKILLS_ROOT}/refunds/SKILL.md").decode()
        assert "Ask for the order id." in body
        # Byte for byte: the script has to be exactly what the shell will run.
        assert document.read_bytes(f"{SKILLS_ROOT}/refunds/reconcile.py") == b"print(1)"

    async def test_the_body_carries_the_name_and_description_the_library_parses(self):
        """The description is what every other agent reads before deciding whether
        to load the skill at all, so it has to be editable - which means it has to
        be in the file rather than implied by the directory."""
        body = render_body(_Skill())

        assert body.startswith("---\nname: refunds\n")
        assert "description: How refunds work." in body

    async def test_a_workspace_that_refuses_a_write_still_runs_the_agent(self):
        """The skills are in the prompt either way, which is how they worked
        before this existed. Failing the run over a file would be a regression
        caused by a convenience."""
        workspace = document_workspace(CappedStateBackend(max_bytes=10))

        state = await materialise(workspace, [_Skill()])

        assert state.written == {}
        assert state.owners == {"refunds": state.owners["refunds"]}

    async def test_a_workspace_that_raises_is_survived_too(self):
        assert (await materialise(_WriteFails(document_workspace()), [_Skill()])).written == {}


class TestCollectingWhatTheAgentChanged:
    async def test_an_untouched_workspace_proposes_nothing(self):
        document, workspace = _document()
        state = await materialise(workspace, [_Skill(resources=[_Resource("notes.md", "hello")])])

        assert await collect_changes(workspace, state) == []

    async def test_an_edited_body_comes_back_as_the_new_body(self):
        skill = _Skill()
        document, workspace = _document()
        state = await materialise(workspace, [skill])

        _write(
            document,
            f"{SKILLS_ROOT}/refunds/SKILL.md",
            "---\nname: refunds\ndescription: How refunds work now.\n---\n\nAsk for the receipt.",
        )
        [change] = await collect_changes(workspace, state)

        assert change.skill_id == skill.id
        assert change.is_new is False
        assert change.description == "How refunds work now."
        assert change.content == "Ask for the receipt."

    async def test_a_new_resource_comes_back_with_the_skill_it_sits_in(self):
        skill = _Skill()
        document, workspace = _document()
        state = await materialise(workspace, [skill])

        _write(document, f"{SKILLS_ROOT}/refunds/checklist.md", "- ask for the id")
        [change] = await collect_changes(workspace, state)

        assert change.resources == {"checklist.md": "- ask for the id"}

    async def test_a_skill_the_agent_invented_has_no_id_to_edit(self):
        """It becomes a *new* skill on approval rather than overwriting one, and
        the difference is a missing id rather than a flag somebody sets."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])

        _write(
            document,
            f"{SKILLS_ROOT}/escalation/SKILL.md",
            "---\nname: escalation\ndescription: When to escalate.\n---\n\nPage the lead.",
        )
        [change] = await collect_changes(workspace, state)

        assert change.name == "escalation"
        assert change.is_new is True

    async def test_a_deleted_resource_is_not_a_proposal(self):
        """Absence cannot be read: a model that never touched the file and one
        that meant to delete it leave the same workspace."""
        document, workspace = _document()
        state = await materialise(
            workspace, [_Skill(resources=[_Resource("a.md", "one"), _Resource("b.md", "two")])]
        )

        _write(document, f"{SKILLS_ROOT}/refunds/a.md", "one")  # unchanged
        # b.md is simply never mentioned again, which is what a delete looks like.
        changes = await collect_changes(workspace, state)

        assert changes == []

    async def test_a_directory_with_no_body_is_refused_rather_than_filled_in(self):
        """Inventing an empty body would propose replacing real instructions with
        nothing."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])

        _write(document, f"{SKILLS_ROOT}/stray/notes.md", "just a file")

        assert await collect_changes(workspace, state) == []

    async def test_a_host_that_did_not_measure_a_file_does_not_break_the_read(self):
        """`size` is `int | None`, and a listing carrying the key with `None` - a
        host that could not measure the file - compared `None` to the cap and raised
        inside the ingestion of a proposal. Found by typing the backend properly."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])

        _write(document, f"{SKILLS_ROOT}/refunds/SKILL.md", "---\nname: refunds\n---\n\nrewritten")

        [change] = await collect_changes(_Unmeasured(workspace), state)

        assert change.content == "rewritten"

    async def test_an_unmeasured_file_past_the_ceiling_is_still_dropped(self):
        """A container's listing carries no sizes, so the ceiling is checked
        against what the file measures - or a file of any size became a proposal."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])

        _write(document, f"{SKILLS_ROOT}/refunds/huge.md", "x" * (300 * 1024))

        assert await collect_changes(_Unmeasured(workspace), state) == []

    async def test_frontmatter_the_model_mangled_is_refused_rather_than_guessed_at(self):
        """The description is what other agents read first; a guess at it is a
        guess at what this skill claims to be."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])

        _write(document, f"{SKILLS_ROOT}/refunds/SKILL.md", "---\n: : :\nnot: [yaml\n---\n\nbody")

        assert await collect_changes(workspace, state) == []

    async def test_frontmatter_that_is_not_a_mapping_is_refused_the_same_way(self):
        """Valid YAML, wrong shape - a list or a sentence where keys were expected."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])

        _write(document, f"{SKILLS_ROOT}/refunds/SKILL.md", "---\n- refunds\n---\n\nbody")

        assert await collect_changes(workspace, state) == []

    async def test_a_body_with_no_frontmatter_proposes_an_empty_description(self):
        """Accepted rather than refused: the instructions are there and readable,
        and a reviewer can see the description is missing and fill it in."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])

        _write(document, f"{SKILLS_ROOT}/refunds/SKILL.md", "Ask for the receipt.")
        [change] = await collect_changes(workspace, state)

        assert change.description == ""
        assert change.content == "Ask for the receipt."

    async def test_a_file_nested_deeper_than_a_skill_belongs_to_no_skill(self):
        """A skill is a directory of files. Treating `/workspace/skills/a/b/c` as `a`'s
        would flatten two paths onto one resource name."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])

        _write(document, f"{SKILLS_ROOT}/refunds/deep/nested.md", "hidden")

        assert await collect_changes(workspace, state) == []

    async def test_a_loose_file_beside_the_skills_belongs_to_no_skill(self):
        """A skill is a directory; a file the agent left directly under the skills
        root has no name to be proposed under."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])

        _write(document, f"{SKILLS_ROOT}/notes.md", "scratch")

        assert await collect_changes(workspace, state) == []

    async def test_a_file_past_the_ceiling_is_dropped_rather_than_truncated(self):
        """Half a script is not a script, and storing it would offer a reviewer
        something that cannot be right."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])

        _write(document, f"{SKILLS_ROOT}/refunds/huge.md", "x" * (300 * 1024))
        changes = await collect_changes(workspace, state)

        assert changes == []

    async def test_a_directory_in_a_skill_is_not_read_as_a_file(self):
        """A listing names directories too; reading one would raise where nothing
        is wrong."""
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])
        _write(document, f"{SKILLS_ROOT}/refunds/SKILL.md", "body")
        document.make_dir(f"{SKILLS_ROOT}/refunds/drafts")

        [change] = await collect_changes(workspace, state)

        assert change.content == "body"

    async def test_a_dot_named_resource_is_proposed_like_any_other(self):
        document, workspace = _document()
        state = await materialise(workspace, [_Skill()])
        _write(document, f"{SKILLS_ROOT}/refunds/.gitignore", "*.tmp")

        [change] = await collect_changes(workspace, state)

        assert change.resources == {".gitignore": "*.tmp"}

    async def test_no_skills_folder_proposes_nothing(self):
        assert (
            await collect_changes(
                document_workspace(), (await materialise(document_workspace(), []))
            )
            == []
        )

    async def test_a_workspace_that_cannot_be_listed_proposes_nothing(self):
        """Which is the same as one that changed nothing - and it runs in the
        `finally` that records what the run cost, so it cannot raise."""

        state = await materialise(_document()[1], [_Skill()])

        assert await collect_changes(_ListingFails(document_workspace()), state) == []


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (f"{SKILLS_ROOT}/refunds/SKILL.md", "refunds"),
        (f"{SKILLS_ROOT}/refunds", None),
        ("/uploads/report.csv", None),
    ],
)
def test_which_skill_a_path_belongs_to(path: str, expected: str | None):
    from app.services.skill_workspace import _skill_of

    assert _skill_of(path) == expected
