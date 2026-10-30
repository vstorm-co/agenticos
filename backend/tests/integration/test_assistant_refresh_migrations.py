"""Upgrade real stored prompts without treating operator edits as stock defaults."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.services.assistant import instructions_fingerprint

pytestmark = pytest.mark.anyio


def migration(name):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prompt_migrations_preserve_edits_and_stamp_only_known_instructions(
    database_url: str,
) -> None:
    stamp = migration("0182_assistant_template_stamp")
    prompts = migration("0183_channel_prompt_defaults")
    engine = create_engine(database_url.replace("+asyncpg", "+psycopg2"))
    schema = f"refresh_test_{uuid4().hex}"
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
            connection.exec_driver_sql(f"SET LOCAL search_path TO {schema}")
            connection.exec_driver_sql(
                "CREATE TABLE agents (id uuid PRIMARY KEY, draft_spec jsonb, current_version_id uuid)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE agent_versions (id uuid PRIMARY KEY, spec jsonb)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE organization_assistants (organization_id uuid PRIMARY KEY, agent_id uuid)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE agent_exposures (id uuid PRIMARY KEY, surface text, prompt text)"
            )
            shipped = (
                (
                    Path(__file__).resolve().parents[1]
                    / "fixtures"
                    / "architect-instructions-before-refresh.md"
                )
                .read_text()
                .strip()
            )
            desktop_shipped = (
                (
                    Path(__file__).resolve().parents[1]
                    / "fixtures"
                    / "architect-instructions-desktop-1.31.0.md"
                )
                .read_text()
                .strip()
            )
            ids = []
            for draft, published in [
                (shipped, shipped),
                ("Our edits", shipped),
                ("Our edits", "Our edits"),
                (shipped, None),
                ("Unknown old instructions", None),
                (desktop_shipped, desktop_shipped),
                (
                    desktop_shipped + "\nOrganization edits.",
                    desktop_shipped + "\nOrganization edits.",
                ),
            ]:
                org_id, agent_id, version_id = (
                    uuid4(),
                    uuid4(),
                    uuid4() if published is not None else None,
                )
                ids.append(org_id)
                if version_id is not None:
                    connection.execute(
                        text("INSERT INTO agent_versions VALUES (:id, CAST(:spec AS jsonb))"),
                        {"id": version_id, "spec": json.dumps({"instructions": published})},
                    )
                connection.execute(
                    text("INSERT INTO agents VALUES (:id, CAST(:draft AS jsonb), :version)"),
                    {
                        "id": agent_id,
                        "draft": json.dumps({"instructions": draft}),
                        "version": version_id,
                    },
                )
                connection.execute(
                    text("INSERT INTO organization_assistants VALUES (:id, :agent)"),
                    {"id": org_id, "agent": agent_id},
                )
            samples = []
            for surface, defaults in prompts.DEFAULTS.items():
                for default in defaults:
                    for before, expected in [
                        (default, None),
                        (
                            "Custom prefix.\n\n" + default + "\n\nCustom suffix.",
                            "Custom prefix.\n\n\n\nCustom suffix.",
                        ),
                    ]:
                        item = uuid4()
                        samples.append((item, expected))
                        connection.execute(
                            text("INSERT INTO agent_exposures VALUES (:id, :surface, :prompt)"),
                            {"id": item, "surface": surface, "prompt": before},
                        )
            for surface, value in [
                ("web", "Only our text"),
                ("slack", "Our altered format"),
                ("mattermost", None),
            ]:
                item = uuid4()
                samples.append((item, value))
                connection.execute(
                    text("INSERT INTO agent_exposures VALUES (:id, :surface, :prompt)"),
                    {"id": item, "surface": surface, "prompt": value},
                )
            with Operations.context(MigrationContext.configure(connection)):
                stamp.upgrade()
                prompts.upgrade()
                recorded = dict(
                    connection.execute(
                        text(
                            "SELECT organization_id, instructions_fingerprint FROM organization_assistants"
                        )
                    ).all()
                )
                digest = instructions_fingerprint(shipped)
                assert [recorded[item] for item in ids] == [
                    digest,
                    digest,
                    None,
                    digest,
                    None,
                    instructions_fingerprint(desktop_shipped),
                    None,
                ]
                actual = dict(
                    connection.execute(text("SELECT id, prompt FROM agent_exposures")).all()
                )
                assert actual == dict(samples)
                # Include bindings created after upgrade, and edits made while
                # defaults were supplied by the newer runner.
                added = {}
                for surface in prompts.DEFAULTS:
                    for value in (
                        None,
                        "",
                        "  Custom additions after upgrade.\n",
                        prompts.DEFAULTS[surface][2] + "\n\nAlready restored.",
                    ):
                        item = uuid4()
                        connection.execute(
                            text("INSERT INTO agent_exposures VALUES (:id, :surface, :prompt)"),
                            {"id": item, "surface": surface, "prompt": value},
                        )
                        added[item] = (surface, value)
                surfaces = dict(
                    connection.execute(text("SELECT id, surface FROM agent_exposures")).all()
                )
                before_rollback = {
                    **actual,
                    **{key: value for key, (surface, value) in added.items()},
                }
                prompts.downgrade()
                restored = dict(
                    connection.execute(text("SELECT id, prompt FROM agent_exposures")).all()
                )
                for item, previous in before_rollback.items():
                    surface = surfaces[item]
                    if surface not in prompts.DEFAULTS:
                        assert restored[item] == previous
                        continue
                    parent = prompts.DEFAULTS[surface][2]
                    assert parent in restored[item]
                    assert restored[item].count(parent) == 1
                    if previous:
                        assert previous in restored[item]
                    else:
                        assert restored[item] == parent
                # Repeated rollback does not duplicate the restored defaults.
                prompts.downgrade()
                assert (
                    dict(connection.execute(text("SELECT id, prompt FROM agent_exposures")).all())
                    == restored
                )
                prompts.upgrade()
                assert dict(
                    connection.execute(text("SELECT id, prompt FROM agent_exposures")).all()
                ) == {
                    item: (prompts.custom_prompt(surfaces[item], value) if value else None)
                    for item, value in restored.items()
                }
                stamp.downgrade()
                columns = tuple(
                    connection.execute(text("SELECT * FROM organization_assistants")).keys()
                )
                assert "instructions_fingerprint" not in columns
            connection.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
    finally:
        engine.dispose()
