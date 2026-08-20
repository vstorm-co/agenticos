"""An explicit `null` on an update must never reach a `NOT NULL` column.

`model_dump(exclude_unset=True)` keeps a field that was **explicitly set to
`None`**. On an `*Update` schema every field is `X | None` because `None` means
"not provided" - so a client sending `{"name": null}` has provided one, the `None`
survives the dump, reaches `setattr` and hits the column. The API's own types say
the request is legal and the answer is a 500 naming a database constraint (#637).

Twenty-four such pairs existed across eleven schemas. They were not twenty-four
bugs: they were one missing function, `db.updates.writable`, because the
alternative is a hand-kept list of field names per service - `agent_embed.py` had
exactly that, five names long - and a new optional field is then a new crash
nobody notices for months.

So this file is a gate rather than a report. What it holds shut is the *next*
optional field, added by somebody who never read the issue:

1. every `*Update` schema is declared here against the row it writes, so a new one
   cannot arrive unnoticed;
2. for every declared pair, `writable` drops each null a column refuses and keeps
   each null a column allows - asserted over the real schemas, not an example;
3. no service dumps an update schema itself, which is the only way to get back to
   the shape this replaced.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import types
from pathlib import Path
from typing import Any, Union, get_args, get_origin

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase

import app.schemas as schemas_package
from app.db.models.agent_embed import AgentEmbed
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_exposure import AgentExposure
from app.db.models.channel_bot import ChannelBot
from app.db.models.context import ContextFile
from app.db.models.conversation import Conversation
from app.db.models.dashboard_layout import DashboardLayout
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.sandbox_connection import SandboxConnection
from app.db.models.skill import Skill, SkillResource
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.db.models.user_slash_command import UserSlashCommand
from app.db.updates import cleared, writable
from app.schemas.agent import AgentDraftUpdate
from app.schemas.agent_embed import EmbedUpdate
from app.schemas.agent_environment import EnvironmentUpdate
from app.schemas.agent_exposure import ExposureUpdate
from app.schemas.channel_bot import ChannelBotUpdate
from app.schemas.context import ContextFileUpdate
from app.schemas.conversation import ConversationUpdate
from app.schemas.dashboard_layout import DashboardLayoutUpdate
from app.schemas.deployment_settings import DeploymentSettingsUpdate
from app.schemas.knowledge_base import KnowledgeBaseUpdate
from app.schemas.mcp_connection import McpConnectionUpdate, OrgMcpConnectionUpdate
from app.schemas.organization import OrganizationMemberUpdate, OrganizationUpdate
from app.schemas.resource_grant import VisibilityUpdate
from app.schemas.sandbox_connection import SandboxConnectionUpdate
from app.schemas.secret import SecretUpdate
from app.schemas.skill import SkillResourceUpdate, SkillUpdate
from app.schemas.sync_source import SyncSourceUpdate
from app.schemas.user import UserUpdate
from app.schemas.user_slash_command import UserSlashCommandUpdate

# Which row each `*Update` schema writes, and `None` where it writes no single
# one. Declared by hand because nothing in the code says it: the pairing lives in
# a service, three call frames from either end. `None` is a claim as much as a
# model is - `AgentDraftUpdate` writes a JSONB spec, and `VisibilityUpdate` writes
# a column plus grant rows - so a schema whose fields *are* columns must not be
# parked there to silence the gate.
UPDATE_TARGETS: dict[type[BaseModel], type[DeclarativeBase] | None] = {
    AgentDraftUpdate: None,
    ChannelBotUpdate: ChannelBot,
    ContextFileUpdate: ContextFile,
    ConversationUpdate: Conversation,
    DashboardLayoutUpdate: DashboardLayout,
    DeploymentSettingsUpdate: DeploymentSettings,
    EmbedUpdate: AgentEmbed,
    EnvironmentUpdate: AgentEnvironment,
    ExposureUpdate: AgentExposure,
    KnowledgeBaseUpdate: KnowledgeBase,
    McpConnectionUpdate: McpConnection,
    OrgMcpConnectionUpdate: McpConnection,
    OrganizationMemberUpdate: OrganizationMember,
    OrganizationUpdate: Organization,
    SandboxConnectionUpdate: SandboxConnection,
    SecretUpdate: OrganizationSecret,
    SkillResourceUpdate: SkillResource,
    SkillUpdate: Skill,
    SyncSourceUpdate: SyncSource,
    UserSlashCommandUpdate: UserSlashCommand,
    UserUpdate: User,
    VisibilityUpdate: None,
}

# What is left, and none of it writes a row. `ingestion_config` merges two Pydantic
# models - `exclude_unset` doing exactly what it is for - and `rag_document` puts an
# override into a JSONB payload, where a null is a value the column can hold.
_DUMP_EXEMPT = {
    "app/services/ingestion_config.py",
    "app/services/rag_document.py",
}

# `exclude_unset=True` anywhere in the call, not `model_dump(exclude_unset=True)`
# literally. The narrow pattern was the first version and it had a hole exactly the
# size of one keyword argument: `model_dump(exclude_unset=True,
# exclude={"clear_allowed_tools"})` in `mcp_connection.py` matched nothing, so two
# services went on writing nulls to `NOT NULL` columns behind a green gate.
_DUMP = re.compile(r"exclude_unset=True")


def _optional(annotation: Any) -> bool:
    return get_origin(annotation) in (Union, types.UnionType) and type(None) in get_args(annotation)


def _import_all(package: types.ModuleType) -> None:
    for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        importlib.import_module(module.name)


def _every_update_schema() -> set[type[BaseModel]]:
    _import_all(schemas_package)
    found: set[type[BaseModel]] = set()
    for module in pkgutil.walk_packages(schemas_package.__path__, schemas_package.__name__ + "."):
        for name, obj in vars(importlib.import_module(module.name)).items():
            if isinstance(obj, type) and issubclass(obj, BaseModel) and name.endswith("Update"):
                found.add(obj)
    return found


def _pairs() -> list[tuple[type[BaseModel], type[DeclarativeBase]]]:
    return [(schema, model) for schema, model in UPDATE_TARGETS.items() if model is not None]


class TestEveryUpdateSchemaIsAccountedFor:
    def test_nothing_new_arrives_unnoticed(self) -> None:
        """A schema absent from the map is a write nobody has checked."""
        undeclared = sorted(
            schema.__name__ for schema in _every_update_schema() - set(UPDATE_TARGETS)
        )

        assert not undeclared, (
            f"`*Update` schemas nothing declares a target for: {undeclared} - add the "
            "model whose row they write, or `None` with the reason they write no "
            "single one"
        )

    def test_nothing_stale_is_left_behind(self) -> None:
        """A schema that was deleted must lose its entry, or the map reads as a
        promise about something that no longer exists."""
        stale = sorted(schema.__name__ for schema in set(UPDATE_TARGETS) - _every_update_schema())

        assert not stale, f"the map names schemas that no longer exist: {stale}"

    def test_the_sweep_can_find_a_schema_at_all(self) -> None:
        """Without this the two tests above pass by discovering nothing."""
        assert EmbedUpdate in _every_update_schema()

    def test_a_target_that_is_none_is_a_claim_and_not_a_parking_space(self) -> None:
        """The one hole the map has, named rather than left implicit: a `None` entry
        says "this writes no single row", and nothing here can prove it. What can be
        checked is the weaker thing - that such a schema has no field which is a
        column on a model of the same-ish name - and it is not worth the guesswork.
        So this test only pins the two that exist today, so a third has to be
        argued for in a diff rather than added quietly.
        """
        assert {schema.__name__ for schema, model in UPDATE_TARGETS.items() if model is None} == {
            "AgentDraftUpdate",
            "VisibilityUpdate",
        }


class TestANullIsDroppedWhereTheColumnRefusesIt:
    @pytest.mark.parametrize(("schema", "model"), _pairs(), ids=lambda arg: arg.__name__)
    def test_no_optional_field_can_write_null_to_a_not_null_column(
        self, schema: type[BaseModel], model: type[DeclarativeBase]
    ) -> None:
        """The gate, over the real schemas rather than an example of one.

        Every optional field is set to `null` at once - which is the request a
        client makes one field at a time - and what comes back must name no column
        that would refuse it.
        """
        optional = [
            field for field, info in schema.model_fields.items() if _optional(info.annotation)
        ]
        if not optional:
            pytest.skip("no optional field, so no null to send")
        columns = model.__table__.columns

        # `model_construct`, not `model_validate`: the payload is every optional
        # field at once, and some schemas have a *required* field beside them
        # (`OrganizationMemberUpdate.role`) that this request would not carry. What
        # is under test is the dropping, and `_fields_set` is what `exclude_unset`
        # reads - so this is the shape of the request without inventing the rest of
        # one.
        sent = schema.model_construct(_fields_set=set(optional), **dict.fromkeys(optional))

        written = writable(sent, over=model)

        refused = sorted(
            field
            for field, value in written.items()
            if value is None and (column := columns.get(field)) is not None and not column.nullable
        )
        assert not refused, (
            f"{schema.__name__} would write null to NOT NULL columns on {model.__name__}: {refused}"
        )

    def test_a_null_a_column_allows_is_kept(self) -> None:
        """The other half, and the reason this is not `exclude_none`: clearing a
        nullable column is a legitimate request, and dropping every null would make
        "remove the description" silently do nothing."""
        written = writable(
            SecretUpdate.model_validate({"description": None}), over=OrganizationSecret
        )

        assert written == {"description": None}

    def test_a_field_that_is_not_a_column_is_passed_through(self) -> None:
        """A service renaming one on the way to the row - `password` becoming
        `hashed_password` - does that after this, so dropping what it does not
        recognise would take the value away before the service ever saw it."""
        written = writable(UserUpdate.model_validate({"password": "hunter22"}), over=User)

        assert written == {"password": "hunter22"}

    def test_a_field_nobody_set_is_absent_either_way(self) -> None:
        assert writable(ConversationUpdate.model_validate({}), over=Conversation) == {}


class TestNothingDumpsAnUpdateItself:
    @pytest.mark.parametrize("package", ["services", "api"])
    def test_the_shape_this_replaced_is_gone(self, package: str) -> None:
        """The only way back to the crash is to write the dump by hand again.

        A grep rather than a type: `exclude_unset` is correct in general and wrong
        only when its result is written to a row, and nothing in the types can tell
        those apart. What the guard can say is that every caller goes through
        `writable`, which reads the column.

        `api` as well as `services`, because the first version of this read services
        alone and `skills.py` dumped in the **route** - so `PATCH /skills/{id}` with
        `{"description": null}` still reached a `NOT NULL` column, which is the whole
        of #637 in the one layer the guard was not looking at.
        """
        root = Path(__file__).resolve().parent.parent
        searched = root / "app" / package
        offenders = sorted(
            str(path.relative_to(root))
            for path in searched.rglob("*.py")
            if str(path.relative_to(root)) not in _DUMP_EXEMPT
            and _DUMP.search(path.read_text(encoding="utf-8"))
        )

        assert not offenders, (
            f"dumping an update schema by hand: {offenders} - use "
            "`app.db.updates.writable`, which drops the nulls the columns refuse"
        )

    def test_the_exemption_still_names_something_real(self) -> None:
        """A stale exemption is a hole with a comment over it."""
        root = Path(__file__).resolve().parent.parent
        for exempt in _DUMP_EXEMPT:
            assert _DUMP.search((root / exempt).read_text(encoding="utf-8")), (
                f"{exempt} no longer dumps anything - drop it from the exemptions"
            )


class TestWhereANullMeansSomethingOtherThanNothing:
    """Two fields where dropping the null is the wrong answer, and one shape for both.

    `writable` drops it, which is right for a column that cannot hold one - the row
    keeps what it had. But "the row keeps what it had" is not always what the caller
    asked for, and the two exceptions are worth naming because both were *found* by
    this conversion breaking them rather than by reading:

    *Reset.* `EmbedUpdate.config` has defaults worth returning to, so dropping the
    key answered "put the look back" by doing nothing at all.

    *Refuse.* An environment is always pinned, so `version_id: null` is a request
    with no valid meaning - and dropping it turned the sentence saying so into
    "Nothing to change", which is true of the row and useless to whoever asked.

    Which of the three a field wants is a judgement `writable` cannot make. What it
    can do is make the judgement visible: a service that needs one calls `cleared`,
    and a reader sees the exception beside the rule.
    """

    def test_a_field_somebody_set_to_null_reads_as_cleared(self) -> None:
        assert cleared(EmbedUpdate.model_validate({"config": None}), "config") is True

    def test_a_field_nobody_mentioned_does_not(self) -> None:
        """The distinction `exclude_unset` is built on, asked directly: absent and
        explicitly null are different requests."""
        assert cleared(EmbedUpdate.model_validate({}), "config") is False

    def test_a_field_set_to_a_value_does_not_either(self) -> None:
        assert cleared(ConversationUpdate.model_validate({"title": "Q3"}), "title") is False
