"""The demo seed: its content, its idempotency, and what it refuses to fake.

The seed exists so the guided first run has a real workspace to show before
the user's own first run lands. What matters is that it creates exactly the
curated content, never twice, that a second run or `--clear` leaves nothing
half-built behind, and that the stored answer can never pass for a real
completed run: it carries no `run_id` and `model_name="demo"`.

Taken from draft PR #209's tests, plus the name-resolution paths this PR adds
so `scripts/quickstart.sh --demo` can seed by the organization name it just
bootstrapped.
"""

import json
import uuid
from contextlib import ExitStack, asynccontextmanager, contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from app.commands.seed_demo import (
    DEMO_ASSISTANT_REPLY,
    DEMO_CONVERSATION_TITLE,
    DEMO_PROJECT_NAME,
    DEMO_USER_PROMPT,
    _find_demo_conversations,
    _find_demo_projects,
    _run,
    seed_demo,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ORG_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()


def _db_context(db):
    @asynccontextmanager
    async def context():
        yield db

    return context


def _named(rows):
    """A lookup result whose `scalars().all()` answers with `rows`."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _result(project):
    """The demo-project lookup: none, or one."""
    return _named([] if project is None else [project])


@pytest.fixture
def db():
    mock = MagicMock()
    mock.execute = AsyncMock(return_value=_result(None))
    mock.delete = AsyncMock()
    mock.flush = AsyncMock()
    return mock


@pytest.fixture
def org():
    org = MagicMock()
    org.id = ORG_ID
    org.name = "Northwind Labs"
    return org


@pytest.fixture
def project():
    project = MagicMock()
    project.id = uuid.uuid4()
    return project


@pytest.fixture
def conversation():
    conversation = MagicMock()
    conversation.id = uuid.uuid4()
    return conversation


def _patch_all(
    db,
    org,
    *,
    existing_project=None,
    existing_conversation=None,
    existing_projects=None,
    existing_conversations=None,
    owner_id=OWNER_ID,
    created_project=None,
    created_conversation=None,
    name_matches=None,
):
    """Patch every repository the seed touches; lookups answer in call order.

    `name_matches` is the answer to the by-name lookup, which runs before
    the project lookup when the organization is given as a name, not an id.
    """
    lookups = []
    if name_matches is not None:
        lookups.append(_named(name_matches))
    projects = (
        existing_projects
        if existing_projects is not None
        else ([] if existing_project is None else [existing_project])
    )
    conversations = (
        existing_conversations
        if existing_conversations is not None
        else ([] if existing_conversation is None else [existing_conversation])
    )
    lookups.append(_named(projects))
    if projects:
        # A clear run looks the conversations up after the projects; a
        # dry-run/second run never reaches them, so the extra answer is unused.
        lookups.append(_named(conversations))
    db.execute = AsyncMock(side_effect=lookups)
    return [
        patch("app.commands.seed_demo.get_db_context", _db_context(db)),
        patch(
            "app.commands.seed_demo.organization_repo.get_by_id",
            new=AsyncMock(return_value=org),
        ),
        patch(
            "app.commands.seed_demo.member_repo.first_owner_id",
            new=AsyncMock(return_value=owner_id),
        ),
        patch(
            "app.commands.seed_demo.project_repo.create",
            new=AsyncMock(return_value=created_project),
        ),
        patch("app.commands.seed_demo.ProjectService.delete", new=AsyncMock()),
        patch(
            "app.commands.seed_demo.conversation_repo.create_conversation",
            new=AsyncMock(return_value=created_conversation),
        ),
        patch(
            "app.commands.seed_demo.conversation_repo.create_message",
            new=AsyncMock(),
        ),
    ]


@contextmanager
def _patched(db, org, **kwargs):
    """Enter every patch; yields the mocks in _patch_all order."""
    with ExitStack() as stack:
        yield [stack.enter_context(p) for p in _patch_all(db, org, **kwargs)]


class TestTheContent:
    def test_the_seed_and_the_start_hub_show_the_same_example(self):
        """The start hub's "what a finished result looks like" panel and the seeded
        conversation must agree word for word, or the demo contradicts itself."""
        en = json.loads((REPO_ROOT / "frontend" / "messages" / "en.json").read_text())
        example = en["start"]["examples"]["meeting"]
        assert example["prompt"] == DEMO_USER_PROMPT
        assert example["result"] == DEMO_ASSISTANT_REPLY

    def test_the_demo_content_names_itself_as_demo(self):
        assert "Demo" in DEMO_PROJECT_NAME
        assert "Demo" in DEMO_CONVERSATION_TITLE


class TestTheCommand:
    @pytest.mark.anyio
    async def test_an_unknown_organization_id_is_refused(self, db, capsys):
        with (
            patch("app.commands.seed_demo.get_db_context", _db_context(db)),
            patch(
                "app.commands.seed_demo.organization_repo.get_by_id",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(click.exceptions.Exit) as refused,
        ):
            await _run(str(ORG_ID), False, False)
        assert refused.value.exit_code == 1
        assert "No organization" in capsys.readouterr().out

    @pytest.mark.anyio
    async def test_an_unknown_organization_name_is_refused(self, db, org, capsys):
        with (
            _patched(db, org, name_matches=[]) as mocks,
            pytest.raises(click.exceptions.Exit) as refused,
        ):
            await _run("No Such Org", False, False)
        assert refused.value.exit_code == 1
        assert "No organization named 'No Such Org'" in capsys.readouterr().out
        mocks[3].assert_not_called()

    @pytest.mark.anyio
    async def test_an_ambiguous_organization_name_is_refused(self, db, org, capsys):
        with (
            _patched(db, org, name_matches=[org, org]) as mocks,
            pytest.raises(click.exceptions.Exit) as refused,
        ):
            await _run("Northwind Labs", False, False)
        assert refused.value.exit_code == 1
        assert "More than one organization is named" in capsys.readouterr().out
        mocks[3].assert_not_called()

    @pytest.mark.anyio
    async def test_a_name_resolves_to_the_organization(
        self, db, org, project, conversation, capsys
    ):
        with _patched(
            db,
            org,
            created_project=project,
            created_conversation=conversation,
            name_matches=[org],
        ) as mocks:
            await _run("Northwind Labs", False, False)
        create_project = mocks[3]
        create_project.assert_awaited_once()
        assert create_project.await_args.kwargs["organization_id"] == ORG_ID
        assert "Created demo workspace" in capsys.readouterr().out

    @pytest.mark.anyio
    async def test_a_dry_run_creates_nothing(self, db, org, capsys):
        with _patched(db, org) as mocks:
            await _run(str(ORG_ID), False, True)
        assert "[DRY RUN]" in capsys.readouterr().out
        mocks[3].assert_not_called()

    @pytest.mark.anyio
    async def test_a_dry_run_with_an_existing_workspace_reports_it(self, db, org, project, capsys):
        with _patched(db, org, existing_project=project) as mocks:
            await _run(str(ORG_ID), False, True)
        assert "[DRY RUN] Demo workspace already exists" in capsys.readouterr().out
        mocks[3].assert_not_called()

    @pytest.mark.anyio
    async def test_a_second_run_creates_nothing(self, db, org, project, capsys):
        with _patched(db, org, existing_project=project) as mocks:
            await _run(str(ORG_ID), False, False)
        assert "already exists" in capsys.readouterr().out
        mocks[3].assert_not_called()

    @pytest.mark.anyio
    async def test_creating_writes_the_project_and_the_two_messages(
        self, db, org, project, conversation, capsys
    ):
        with _patched(db, org, created_project=project, created_conversation=conversation) as mocks:
            await _run(str(ORG_ID), False, False)
        create_project = mocks[3]
        create_project.assert_awaited_once()
        kwargs = create_project.await_args.kwargs
        assert kwargs["name"] == DEMO_PROJECT_NAME
        assert kwargs["organization_id"] == ORG_ID
        assert kwargs["owner_user_id"] == OWNER_ID
        assert kwargs["visibility"] == "org"
        assert kwargs["backend"] == "state"
        mocks[5].assert_awaited_once_with(
            db,
            organization_id=ORG_ID,
            user_id=OWNER_ID,
            title=DEMO_CONVERSATION_TITLE,
            project_id=project.id,
        )
        create_message = mocks[6]
        assert create_message.await_count == 2
        user_call, assistant_call = create_message.await_args_list
        assert user_call.kwargs["role"] == "user"
        assert user_call.kwargs["content"] == DEMO_USER_PROMPT
        # The stored answer must never pass for a real run: no run id, and a
        # model name that says plainly no model ran.
        assert assistant_call.kwargs["role"] == "assistant"
        assert assistant_call.kwargs["content"] == DEMO_ASSISTANT_REPLY
        assert assistant_call.kwargs["model_name"] == "demo"
        assert "run_id" not in assistant_call.kwargs
        assert "Created demo workspace" in capsys.readouterr().out

    @pytest.mark.anyio
    async def test_clear_removes_the_conversation_before_the_project(
        self, db, org, project, conversation
    ):
        with _patched(
            db, org, existing_project=project, existing_conversation=conversation
        ) as mocks:
            await _run(str(ORG_ID), True, False)
        # Deleting the project alone would only detach the chat (its project
        # foreign key is SET NULL), leaving an ordinary chat behind.
        db.delete.assert_awaited_once_with(conversation)
        # The project goes through the service, so its grants, tasks, triggers
        # and audit entry are cleaned up too.
        mocks[4].assert_awaited_once()
        ctx, project_id = mocks[4].await_args.args
        assert (ctx.organization_id, ctx.user_id) == (ORG_ID, OWNER_ID)
        assert project_id == project.id

    @pytest.mark.anyio
    async def test_clear_with_a_project_but_no_conversation_removes_only_the_project(
        self, db, org, project
    ):
        with _patched(db, org, existing_project=project) as mocks:
            await _run(str(ORG_ID), True, False)
        db.delete.assert_not_called()
        mocks[4].assert_awaited_once()

    @pytest.mark.anyio
    async def test_clear_removes_every_duplicate_and_renamed_chat(self, db, org, capsys):
        first, second = MagicMock(), MagicMock()
        first.id, second.id = uuid.uuid4(), uuid.uuid4()
        renamed_a, renamed_b = MagicMock(), MagicMock()
        with _patched(
            db,
            org,
            existing_projects=[first, second],
            existing_conversations=[renamed_a, renamed_b],
        ) as mocks:
            await _run(str(ORG_ID), True, False)
        assert [c.args[0] for c in db.delete.await_args_list] == [renamed_a, renamed_b]
        assert [c.args[1] for c in mocks[4].await_args_list] == [first.id, second.id]
        assert "Removed 2 demo workspace(s)" in capsys.readouterr().out

    @pytest.mark.anyio
    async def test_clear_without_an_owner_exits_non_zero_and_deletes_nothing(
        self, db, org, project
    ):
        with (
            _patched(db, org, existing_project=project, owner_id=None) as mocks,
            pytest.raises(click.exceptions.Exit) as refused,
        ):
            await _run(str(ORG_ID), True, False)
        assert refused.value.exit_code == 1
        db.delete.assert_not_called()
        mocks[4].assert_not_called()

    @pytest.mark.anyio
    async def test_the_lookups_are_scoped_to_what_the_seed_wrote(self, db):
        db.execute = AsyncMock(side_effect=[_named([]), _named([])])
        assert await _find_demo_projects(db, ORG_ID) == []
        assert (
            await _find_demo_conversations(db, organization_id=ORG_ID, project_ids=[uuid.uuid4()])
            == []
        )
        projects_sql, conversations_sql = (
            str(c.args[0].whereclause) for c in db.execute.await_args_list
        )
        # Name alone is not enough to claim a project; a title alone is not
        # enough to claim a chat (it can be renamed).
        assert "projects.description" in projects_sql
        assert "projects.backend" in projects_sql
        assert "messages.model_name" in conversations_sql
        assert "conversations.title" not in conversations_sql

    @pytest.mark.anyio
    async def test_clear_with_nothing_seeded_is_a_no_op(self, db, org, capsys):
        with _patched(db, org) as mocks:
            await _run(str(ORG_ID), True, False)
        assert "No demo workspace to remove" in capsys.readouterr().out
        mocks[4].assert_not_called()

    def test_the_click_command_wires_the_options(self, db):
        # The command itself runs against a database; the context is patched
        # so this only proves the click wiring reaches the resolver.
        with (
            patch("app.commands.seed_demo.get_db_context", _db_context(db)),
            patch(
                "app.commands.seed_demo.organization_repo.get_by_id",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = CliRunner().invoke(seed_demo, ["00000000-0000-4000-8000-000000000001"])
        # A refused organization must fail the process, or `quickstart.sh --demo`
        # would report success for a workspace that was never seeded.
        assert result.exit_code == 1
        assert "No organization" in result.output
