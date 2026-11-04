"""User and agent references are checked on insert, update and schema defaults."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.organization import OrganizationMember
from app.schemas.virtual_table import (
    ColumnInput,
    DocumentTemplate,
    RecordCreate,
    RecordUpdate,
    SchemaUpdate,
    TableCreate,
)
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables.exceptions import InvalidRecordError, InvalidSchemaError
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


async def test_reference_membership_and_agent_visibility_apply_to_writes_and_defaults(
    db: AsyncSession,
):
    owner, colleague = await make_user(db), await make_user(db)
    org, foreign = await make_org(db, owner=owner), await make_org(db, owner=colleague)
    ours = Agent(organization_id=org.id, owner_user_id=owner.id, name="Writer", slug="writer")
    hidden = Agent(
        organization_id=org.id, owner_user_id=colleague.id, name="Private", slug="private"
    )
    theirs = Agent(
        organization_id=foreign.id, owner_user_id=colleague.id, name="Foreign", slug="foreign"
    )
    db.add_all([ours, hidden, theirs])
    await db.flush()
    ctx = ctx_for(owner, org, "member")
    service = VirtualTableService(db)
    table = await service.create_table(
        ctx,
        TableCreate(
            name="Assignments",
            columns=[
                ColumnInput(label="Owner", type="user"),
                ColumnInput(label="People", type="multi_user"),
                ColumnInput(label="Agent", type="agent"),
                ColumnInput(label="Agents", type="multi_agent"),
            ],
        ),
    )
    person, people, agent, agents = [str(column.id) for column in table.columns]
    written = await service.create_record(
        ctx,
        table.id,
        RecordCreate(
            values={
                person: str(owner.id),
                people: [str(owner.id)],
                agent: str(ours.id),
                agents: [str(ours.id)],
            }
        ),
    )
    assert written.record.values[person] == str(owner.id)
    for key, value in [
        (person, str(colleague.id)),
        (people, [str(colleague.id)]),
        (agent, str(hidden.id)),
        (agent, str(theirs.id)),
        (agents, [str(ours.id), str(theirs.id)]),
    ]:
        with pytest.raises(InvalidRecordError):
            await service.update_record(
                ctx,
                table.id,
                written.record.id,
                RecordUpdate(values={key: value}, expected_revision=written.record.revision),
            )
    with pytest.raises(InvalidSchemaError):
        await service.create_table(
            ctx,
            TableCreate(
                name="Invalid default",
                columns=[ColumnInput(label="Owner", type="user", default=str(colleague.id))],
            ),
        )
    db.add(OrganizationMember(organization_id=org.id, user_id=colleague.id, role="member"))
    await db.flush()
    updated = await service.update_record(
        ctx,
        table.id,
        written.record.id,
        RecordUpdate(
            values={people: [str(owner.id), str(colleague.id)]},
            expected_revision=written.record.revision,
        ),
    )
    assert updated.record.values[people] == [str(owner.id), str(colleague.id)]


async def test_a_record_naming_someone_outside_the_organization_is_never_inserted(
    db: AsyncSession,
):
    owner, outsider = await make_user(db), await make_user(db)
    org = await make_org(db, owner=owner)
    await make_org(db, owner=outsider)
    ctx = ctx_for(owner, org, "member")
    service = VirtualTableService(db)
    table = await service.create_table(
        ctx, TableCreate(name="Assignments", columns=[ColumnInput(label="Owner", type="user")])
    )
    person = str(table.columns[0].id)

    with pytest.raises(InvalidRecordError):
        await service.create_record(ctx, table.id, RecordCreate(values={person: str(outsider.id)}))

    assert (await service.list_records(ctx, table.id)).items == []


async def test_a_saved_default_template_applies_to_new_records_and_never_rewrites_existing_ones(
    db: AsyncSession,
):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    service = VirtualTableService(db)
    start = DocumentTemplate(id=uuid4(), name="Team brief", body="# Goal\n")
    table = await service.create_table(
        ctx,
        TableCreate(
            name="Documents",
            columns=[
                ColumnInput(
                    label="Notes",
                    type="rich_text",
                    document_templates=[start],
                    default_template_id=start.id,
                )
            ],
        ),
    )
    key = str(table.columns[0].id)
    first = await service.create_record(ctx, table.id, RecordCreate(values={}))
    assert first.record.values[key] == start.body
    changed = start.model_copy(update={"body": "# New goal\n"})
    schema = await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(
            expected_version=table.schema_version,
            columns=[
                ColumnInput(
                    id=table.columns[0].id,
                    label="Notes",
                    type="rich_text",
                    document_templates=[changed],
                    default_template_id=start.id,
                )
            ],
        ),
    )
    assert schema.columns[0].default == changed.body
    second = await service.create_record(ctx, table.id, RecordCreate(values={}))
    assert second.record.values[key] == changed.body
    assert (await service.get_record(ctx, table.id, first.record.id)).values[key] == start.body
