"""Presentation marks are finite, nullable metadata, never an execution change."""

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import DeclarativeBase

from app.db.models.virtual_table import VirtualTable
from app.db.models.workflow import Workflow
from app.db.updates import writable
from app.schemas.virtual_table import TableCreate, TableUpdate
from app.schemas.workflow import WorkflowCreate, WorkflowUpdate


@pytest.mark.parametrize("schema", [TableCreate, TableUpdate, WorkflowCreate, WorkflowUpdate])
@pytest.mark.parametrize("icon", ["table", "workflow", "calendar"])
def test_resource_marks_are_accepted_by_create_and_edit(
    schema: type[BaseModel], icon: object
) -> None:
    data = schema(name="Example", icon=icon)
    assert data.model_dump()["icon"] == icon


@pytest.mark.parametrize("schema", [TableCreate, TableUpdate, WorkflowCreate, WorkflowUpdate])
@pytest.mark.parametrize("icon", ["<svg onload=alert(1)>", "other-icon", 3])
def test_resource_marks_reject_unregistered_names_and_markup(
    schema: type[BaseModel], icon: object
) -> None:
    with pytest.raises(ValidationError):
        schema(name="Example", icon=icon)


@pytest.mark.parametrize("schema, model", [(TableUpdate, VirtualTable), (WorkflowUpdate, Workflow)])
def test_reset_is_explicit_and_an_omitted_mark_is_preserved(
    schema: type[BaseModel], model: type[DeclarativeBase]
) -> None:
    assert writable(schema(icon=None), over=model) == {"icon": None}
    assert writable(schema(), over=model) == {}
