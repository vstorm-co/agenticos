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
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic_ai_backends import StateBackend

from app.agents.capabilities.sandbox._capped import CappedStateBackend
from app.services.skill_workspace import (
    SKILLS_ROOT,
    collect_changes,
    materialise,
    render_body,
)


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


def _backend() -> StateBackend:
    return StateBackend()


class TestWritingSkillsIntoTheWorkspace:
    def test_the_body_and_every_resource_land_beside_each_other(self):
        """Beside each other because that is the whole feature: a script the model
        could previously only quote is now a path its shell can run."""
        skill = _Skill(resources=[_Resource("reconcile.py", "print(1)")])
        backend = _backend()

        materialise(backend, [skill])

        assert "Ask for the order id." in backend.read(f"{SKILLS_ROOT}/refunds/SKILL.md")
        # `read_bytes` because the toolset's `read` numbers lines for a model to
        # quote, and the script has to be exactly what the shell will run.
        assert backend.read_bytes(f"{SKILLS_ROOT}/refunds/reconcile.py") == b"print(1)"

    def test_the_body_carries_the_name_and_description_the_library_parses(self):
        """The description is what every other agent reads before deciding whether
        to load the skill at all, so it has to be editable - which means it has to
        be in the file rather than implied by the directory."""
        body = render_body(_Skill())

        assert body.startswith("---\nname: refunds\n")
        assert "description: How refunds work." in body

    def test_a_workspace_that_refuses_a_write_still_runs_the_agent(self):
        """The skills are in the prompt either way, which is how they worked
        before this existed. Failing the run over a file would be a regression
        caused by a convenience."""
        backend = CappedStateBackend(StateBackend(), max_bytes=10)

        state = materialise(backend, [_Skill()])

        assert state.written == {}
        assert state.owners == {"refunds": state.owners["refunds"]}

    def test_a_backend_that_raises_is_survived_too(self):
        class _Broken:
            def write(self, path, content):
                raise RuntimeError("no")

        assert materialise(_Broken(), [_Skill()]).written == {}


class TestCollectingWhatTheAgentChanged:
    def test_an_untouched_workspace_proposes_nothing(self):
        backend = _backend()
        state = materialise(backend, [_Skill(resources=[_Resource("notes.md", "hello")])])

        assert collect_changes(backend, state) == []

    def test_an_edited_body_comes_back_as_the_new_body(self):
        skill = _Skill()
        backend = _backend()
        state = materialise(backend, [skill])

        backend.write(
            f"{SKILLS_ROOT}/refunds/SKILL.md",
            "---\nname: refunds\ndescription: How refunds work now.\n---\n\nAsk for the receipt.",
        )
        [change] = collect_changes(backend, state)

        assert change.skill_id == skill.id
        assert change.is_new is False
        assert change.description == "How refunds work now."
        assert change.content == "Ask for the receipt."

    def test_a_new_resource_comes_back_with_the_skill_it_sits_in(self):
        skill = _Skill()
        backend = _backend()
        state = materialise(backend, [skill])

        backend.write(f"{SKILLS_ROOT}/refunds/checklist.md", "- ask for the id")
        [change] = collect_changes(backend, state)

        assert change.resources == {"checklist.md": "- ask for the id"}

    def test_a_skill_the_agent_invented_has_no_id_to_edit(self):
        """It becomes a *new* skill on approval rather than overwriting one, and
        the difference is a missing id rather than a flag somebody sets."""
        backend = _backend()
        state = materialise(backend, [_Skill()])

        backend.write(
            f"{SKILLS_ROOT}/escalation/SKILL.md",
            "---\nname: escalation\ndescription: When to escalate.\n---\n\nPage the lead.",
        )
        [change] = collect_changes(backend, state)

        assert change.name == "escalation"
        assert change.is_new is True

    def test_a_deleted_resource_is_not_a_proposal(self):
        """Absence cannot be read: a model that never touched the file and one
        that meant to delete it leave the same workspace."""
        backend = _backend()
        state = materialise(
            backend, [_Skill(resources=[_Resource("a.md", "one"), _Resource("b.md", "two")])]
        )

        backend.write(f"{SKILLS_ROOT}/refunds/a.md", "one")  # unchanged
        # b.md is simply never mentioned again, which is what a delete looks like.
        changes = collect_changes(backend, state)

        assert changes == []

    def test_a_directory_with_no_body_is_refused_rather_than_filled_in(self):
        """Inventing an empty body would propose replacing real instructions with
        nothing."""
        backend = _backend()
        state = materialise(backend, [_Skill()])

        backend.write(f"{SKILLS_ROOT}/stray/notes.md", "just a file")

        assert collect_changes(backend, state) == []

    def test_frontmatter_the_model_mangled_is_refused_rather_than_guessed_at(self):
        """The description is what other agents read first; a guess at it is a
        guess at what this skill claims to be."""
        backend = _backend()
        state = materialise(backend, [_Skill()])

        backend.write(f"{SKILLS_ROOT}/refunds/SKILL.md", "---\n: : :\nnot: [yaml\n---\n\nbody")

        assert collect_changes(backend, state) == []

    def test_a_body_with_no_frontmatter_proposes_an_empty_description(self):
        """Accepted rather than refused: the instructions are there and readable,
        and a reviewer can see the description is missing and fill it in."""
        backend = _backend()
        state = materialise(backend, [_Skill()])

        backend.write(f"{SKILLS_ROOT}/refunds/SKILL.md", "Ask for the receipt.")
        [change] = collect_changes(backend, state)

        assert change.description == ""
        assert change.content == "Ask for the receipt."

    def test_a_file_nested_deeper_than_a_skill_belongs_to_no_skill(self):
        """A skill is a directory of files. Treating `/skills/a/b/c` as `a`'s
        would flatten two paths onto one resource name."""
        backend = _backend()
        state = materialise(backend, [_Skill()])

        backend.write(f"{SKILLS_ROOT}/refunds/deep/nested.md", "hidden")

        assert collect_changes(backend, state) == []

    def test_a_file_past_the_ceiling_is_dropped_rather_than_truncated(self):
        """Half a script is not a script, and storing it would offer a reviewer
        something that cannot be right."""
        backend = _backend()
        state = materialise(backend, [_Skill()])

        backend.write(f"{SKILLS_ROOT}/refunds/huge.md", "x" * (300 * 1024))
        changes = collect_changes(backend, state)

        assert changes == []

    def test_a_directory_in_the_listing_is_not_read_as_a_file(self):
        """`StateBackend` reports only files; a container-backed workspace lists a
        real filesystem, where `/skills/refunds` is itself an entry. Reading it
        would raise where nothing is wrong."""

        class _WithDirectories:
            def glob_info(self, pattern):
                return [
                    {"path": f"{SKILLS_ROOT}/refunds", "is_dir": True, "size": 0},
                    {"path": f"{SKILLS_ROOT}/refunds/SKILL.md", "is_dir": False, "size": 4},
                ]

            def read_bytes(self, path):
                assert path.endswith("SKILL.md")
                return b"body"

        state = materialise(_backend(), [_Skill()])

        [change] = collect_changes(_WithDirectories(), state)

        assert change.content == "body"

    def test_a_workspace_that_cannot_be_listed_proposes_nothing(self):
        """Which is the same as one that changed nothing - and it runs in the
        `finally` that records what the run cost, so it cannot raise."""

        class _Broken:
            def glob_info(self, pattern):
                raise RuntimeError("the service is down")

        state = materialise(_backend(), [_Skill()])

        assert collect_changes(_Broken(), state) == []


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
