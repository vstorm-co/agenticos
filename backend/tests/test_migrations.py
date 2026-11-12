"""Migration tests - verify Alembic upgrade/downgrade cycle.

These tests ensure that:
1. All migrations can be applied (upgrade head)
2. All migrations can be rolled back (downgrade base)
3. The upgrade/downgrade cycle is idempotent

**They run against a database of their own, and that is not a nicety.**
`downgrade base` drops every table. These tests used to inherit whatever
`POSTGRES_DB` resolved to - which, in a checkout with a populated `.env`, is the
developer's working database. An ordinary `pytest` run emptied it: model tables
gone, `alembic_version` recreated by the upgrade that followed, and nothing in
the output to say so. The name below is the fix, and it is passed explicitly to
each subprocess rather than left to the environment to get right.

**That database is created here, and dropped again when the module is done.** It
used to have to exist already: `alembic current` was run for its side effect of
failing, and a missing database became a module-level skip. Nothing in the
repository ever created it - the docstring saying so named `make test-migrations`,
which cycles the chain against whatever `POSTGRES_DB` says and never touches this
name - so every test here skipped on every CI run this project has ever had, and a
build stayed green over four assertions nobody was making (#234). A skip meaning
"no Postgres on this laptop" and a skip meaning "nobody has ever answered this"
read identically in pytest's output, and only one of them is acceptable on a
runner; `_demand_a_server` below is where they are told apart.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.db.models.session import Session
from app.db.models.user import User
from app.services.session import SessionService, hash_token

# Owned by this module alone, and by this run of it. Not the integration suite's
# database either: that one builds its schema from the models with `create_all`,
# and alembic finds those tables already present and fails on the first `CREATE
# TABLE`. The process id carries the same weight it does in `tests/conftest.py` -
# this module drops the database it names, so a constant name would mean two runs
# on one machine (two worktrees, or a `make test` beside this one) dropping each
# other's mid-upgrade (#189).
MIGRATION_DATABASE = f"agenticos_migrations_test_p{os.getpid()}"

# Where `CREATE DATABASE` and `DROP DATABASE` are issued from, neither of which
# can run from inside the database it names. Every Postgres image this project
# uses ships it.
_MAINTENANCE_DATABASE = "postgres"


def _url(database: str) -> str:
    """The DSN alembic builds, pointed at a different database on that server.

    Derived from `settings` rather than from `os.environ` so this module and the
    subprocesses it starts cannot disagree about the host, the user or the
    password: `alembic/env.py` builds its URL from the same place, and a laptop
    keeps those three in `backend/.env` rather than in the environment.
    """
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _env() -> dict[str, str]:
    """The environment each alembic subprocess runs in.

    `POSTGRES_DB` is forced rather than defaulted: a default is something an
    outer environment can override, and what it would override is the guard
    that keeps `downgrade base` away from a real database.
    """
    return {**os.environ, "POSTGRES_DB": MIGRATION_DATABASE}


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=".",
        env=_env(),
        timeout=120,
    )


def _why_the_server_did_not_answer(url: str) -> str | None:
    """`None` when the server answers, otherwise the reason it did not.

    The reason is carried out rather than flattened to a bool because a server
    that is up and refusing - a wrong password, a database still in recovery -
    is a third case, and reporting it as the two below sends the reader to the
    wrong place. Telling those apart is the whole job of `_demand_a_server`.
    """
    engine = create_engine(url)
    try:
        with engine.connect():
            return None
    except Exception as exc:  # Any failure to connect is the answer, whatever it was.
        return str(exc).strip()
    finally:
        engine.dispose()


def _outside_a_transaction(url: str, statement: str) -> None:
    """Run one statement with no transaction around it.

    `CREATE DATABASE` and `DROP DATABASE` are refused inside one, and SQLAlchemy
    opens a transaction for anything else.
    """
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


def _demand_a_server(url: str) -> None:
    """Skip where no database can answer, and refuse to skip where one must.

    On a laptop without Docker, skipping is the whole point: `make test` still
    runs everything else. In CI the Postgres service container is declared, so an
    unreachable server means it failed to start - and a skip is then a green build
    over a migration chain nobody applied, which is exactly the failure this
    module was already reporting silently.
    """
    reason = _why_the_server_did_not_answer(url)
    if reason is None:
        return
    if os.getenv("CI"):
        raise RuntimeError(
            f"No database reachable at {url} but CI is set, so the Postgres "
            f"service container did not come up or is refusing us: {reason}. "
            "Refusing to skip the migration suite and report a green build."
        )
    pytest.skip(f"No database reachable ({reason}) - start one with `make docker-db`")


@pytest.fixture(scope="module", autouse=True)
def migration_database() -> Iterator[None]:
    """The database these tests run against, for as long as they need it.

    Creating one is a privileged act, and this module used to refuse to perform
    one on that ground. The refusal cost more than it bought: nothing else created
    the database either, so the suite skipped everywhere rather than running
    somewhere. `CREATE DATABASE` needs no privilege the migrations do not already
    have, `tests/integration/conftest.py` owns its database's lifecycle the same
    way, and the name is a literal with this process's id on it - not something an
    environment variable can steer at a real database, which is what the guard in
    that conftest exists to catch.

    The drop before the create reclaims a leftover from a run that was killed
    outright. That is the only way one survives, since the teardown below runs
    even when the suite fails.
    """
    maintenance = _url(_MAINTENANCE_DATABASE)
    _demand_a_server(maintenance)

    drop = f'DROP DATABASE IF EXISTS "{MIGRATION_DATABASE}" WITH (FORCE)'
    _outside_a_transaction(maintenance, drop)
    _outside_a_transaction(maintenance, f'CREATE DATABASE "{MIGRATION_DATABASE}"')
    try:
        yield
    finally:
        # FORCE because a connection outliving its subprocess would otherwise
        # leave the database behind. Nobody else ever connects to it.
        _outside_a_transaction(maintenance, drop)


def test_delete_crosslink_migration_preserves_rows_and_defers_only_checks() -> None:
    """Both cascade orders work on migrated data; dangling references still fail."""
    from app.db.models.agent import Agent, AgentVersion
    from app.db.models.agent_environment import AgentEnvironment
    from app.db.models.agent_trigger import AgentTrigger
    from app.db.models.artifact import Artifact
    from app.db.models.conversation import Conversation

    for action, revision in (
        ("upgrade", "head"),
        ("downgrade", "0304_merge_evals_platform"),
    ):
        result = _alembic(action, revision)
        assert result.returncode == 0, result.stderr

    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with DatabaseSession(engine, expire_on_commit=False) as db:
            creator = User(email=f"{uuid4()}@example.com", hashed_password="x")
            owner = User(email=f"{uuid4()}@example.com", hashed_password="x")
            db.add_all([creator, owner])
            db.flush()
            # This is the 0304 schema, before columns added by later migrations.
            org_id = uuid4()
            db.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, is_personal, created_by_user_id) "
                    "VALUES (:id, 'Crosslinks', :slug, false, :creator)"
                ),
                {"id": org_id, "slug": f"crosslinks-{org_id}", "creator": creator.id},
            )
            agent = Agent(organization_id=org_id, name="Reporter", slug=f"reporter-{uuid4()}")
            chat = Conversation(organization_id=org_id, user_id=owner.id, title="Private")
            db.add_all([agent, chat])
            db.flush()
            version = AgentVersion(organization_id=org_id, agent_id=agent.id, version=1, spec={})
            db.add(version)
            db.flush()
            environment = AgentEnvironment(
                organization_id=org_id, agent_id=agent.id, version_id=version.id, name="staging"
            )
            db.add(environment)
            db.flush()
            page = Artifact(
                organization_id=org_id,
                agent_id=agent.id,
                environment_id=environment.id,
                name="report",
                title="Report",
            )
            routine = AgentTrigger(
                organization_id=org_id,
                agent_id=agent.id,
                created_by_user_id=owner.id,
                prompt="Report",
                interval_seconds=300,
                next_fire_at=datetime.now(UTC),
                answer_to="conversation",
                delivery_conversation_id=chat.id,
            )
            db.add_all([page, routine])
            db.commit()
            owner_id, agent_id = owner.id, agent.id
            page_id, routine_id = page.id, routine.id
            environment_id, chat_id = environment.id, chat.id

        constraints = (
            "agent_triggers_delivery_conversation_id_fkey",
            "artifacts_environment_id_fkey",
        )
        # Per parent table: its SET NULL key, then its cascade, each (table, name, column).
        cascades = (
            (
                "users",
                (
                    (
                        "agent_triggers",
                        "agent_triggers_created_by_user_id_fkey",
                        "created_by_user_id",
                    ),
                    ("conversations", "conversations_user_id_fkey", "user_id"),
                ),
                delete(User).where(User.id == owner_id),
                constraints[0],
            ),
            (
                "agents",
                (
                    ("artifacts", "artifacts_agent_id_fkey", "agent_id"),
                    ("agent_environments", "agent_environments_agent_id_fkey", "agent_id"),
                ),
                delete(Agent).where(Agent.id == agent_id),
                constraints[1],
            ),
        )

        def cascade_last(
            db: DatabaseSession, parent: str, keys: tuple[tuple[str, str, str], ...]
        ) -> None:
            """Re-create the SET NULL key, then the cascade, so the cascade fires last.

            A table's triggers fire in name order, and an RI trigger is named after its
            OID, so the comparison is textual: once the cluster's OID counter gains a
            digit, a newly created trigger sorts before every older one. Re-creating
            both keys gives them neighbouring OIDs, whatever the counter has reached.
            """
            for (table, name, column), action in zip(keys, ("SET NULL", "CASCADE"), strict=True):
                db.execute(
                    text(
                        f"ALTER TABLE {table} DROP CONSTRAINT {name}, ADD CONSTRAINT {name} "
                        f"FOREIGN KEY ({column}) REFERENCES {parent}(id) ON DELETE {action}"
                    )
                )
            fired = db.scalars(
                text(
                    "SELECT c.confdeltype FROM pg_trigger t "
                    "JOIN pg_constraint c ON c.oid = t.tgconstraint "
                    "WHERE t.tgrelid = CAST(:parent AS regclass) "
                    "AND c.conname IN (:set_null, :cascade) ORDER BY t.tgname"
                ),
                {"parent": parent, "set_null": keys[0][1], "cascade": keys[1][1]},
            ).all()
            assert fired == ["n", "n", "c", "c"]

        # Prove the old, migrated schema has the same defect as create_all.
        for parent, keys, deletion, constraint in cascades:
            with DatabaseSession(engine) as db:
                cascade_last(db, parent, keys)
                # Unchanged FK columns are rechecked when this transaction has
                # already written the surviving row, as in the integration tests.
                db.execute(
                    update(AgentTrigger)
                    .where(AgentTrigger.id == routine_id)
                    .values(prompt="Updated report")
                )
                db.execute(
                    update(Artifact).where(Artifact.id == page_id).values(title="Updated report")
                )
                with pytest.raises(IntegrityError, match=constraint):
                    db.execute(deletion)

        for action, revision, deferred in (
            ("upgrade", "head", True),
            ("downgrade", "0304_merge_evals_platform", False),
            ("upgrade", "head", True),
        ):
            result = _alembic(action, revision)
            assert result.returncode == 0, result.stderr
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT conname, condeferrable, condeferred, confdeltype FROM pg_constraint WHERE conname IN (:routine, :page)"
                    ),
                    {"routine": constraints[0], "page": constraints[1]},
                ).all()
                assert len(rows) == 2
                assert all(
                    row.condeferrable == deferred
                    and row.condeferred == deferred
                    and row.confdeltype == "n"
                    for row in rows
                )

        for reordered in (False, True):
            with DatabaseSession(engine) as db:
                assert (
                    db.scalar(select(Artifact.environment_id).where(Artifact.id == page_id))
                    == environment_id
                )
                assert (
                    db.scalar(
                        select(AgentTrigger.delivery_conversation_id).where(
                            AgentTrigger.id == routine_id
                        )
                    )
                    == chat_id
                )
                if reordered:
                    for parent, keys, _, _ in cascades:
                        cascade_last(db, parent, keys)
                db.execute(
                    update(AgentTrigger)
                    .where(AgentTrigger.id == routine_id)
                    .values(prompt="Updated report")
                )
                db.execute(
                    update(Artifact).where(Artifact.id == page_id).values(title="Updated report")
                )
                db.execute(delete(User).where(User.id == owner_id))
                db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                assert (
                    db.scalar(
                        select(AgentTrigger.delivery_conversation_id).where(
                            AgentTrigger.id == routine_id
                        )
                    )
                    is None
                )
                db.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                db.execute(delete(Agent).where(Agent.id == agent_id))
                db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                surviving_page = db.get(Artifact, page_id)
                assert surviving_page is not None
                assert surviving_page.agent_id is None
                assert surviving_page.environment_id is None
                # Roll back rows and reordered constraints before the next case.

        for statement, constraint in (
            (
                update(AgentTrigger)
                .where(AgentTrigger.id == routine_id)
                .values(delivery_conversation_id=uuid4()),
                constraints[0],
            ),
            (
                update(Artifact).where(Artifact.id == page_id).values(environment_id=uuid4()),
                constraints[1],
            ),
        ):
            with DatabaseSession(engine) as db:
                db.execute(statement)
                with pytest.raises(IntegrityError, match=constraint):
                    db.commit()
        check = _alembic("check")
        assert check.returncode == 0, check.stderr
    finally:
        engine.dispose()


class TestMigrations:
    """Test Alembic migration integrity."""

    def test_upgrade_head(self):
        """Test that all migrations can be applied successfully."""
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, f"Migration upgrade failed:\n{result.stderr}"

    def test_downgrade_base(self):
        """Test that all migrations can be rolled back."""
        # First upgrade to head
        up = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd=".",
            env=_env(),
        )
        assert up.returncode == 0, f"Migration upgrade failed:\n{up.stderr}"

        # Then downgrade to base
        down = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            capture_output=True,
            text=True,
            cwd=".",
            env=_env(),
        )
        assert down.returncode == 0, f"Migration downgrade failed:\n{down.stderr}"

    def test_upgrade_downgrade_cycle(self):
        """Test that upgrade → downgrade → upgrade produces consistent state."""
        for action, target in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
            result = _alembic(action, target)
            assert result.returncode == 0, f"alembic {action} {target} failed:\n{result.stderr}"

    def test_current_matches_head(self):
        """Test that current migration revision matches head after upgrade."""
        up = _alembic("upgrade", "head")
        assert up.returncode == 0, f"Migration upgrade failed:\n{up.stderr}"

        result = _alembic("current")
        assert result.returncode == 0
        assert "(head)" in result.stdout, (
            f"Current revision is not at head:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


@pytest.mark.parametrize(
    "starting_revision",
    [
        "0248_merge_self_improvement",
        "0250_discord_channel",
        "0252_index_rag_parent_doc_id",
        "0253_helper_snapshots",
        "0254_merge_eval_rag_index",
        "0295_tool_approval_consent",
        "0296_merge_evals_main",
        "0303_merge_workflow_onboarding",
        "0312_skill_check_reasons",
        "0314_tool_approval_always_asks",
        "0306_shared_page_attribution",
    ],
)
def test_improvement_merge_upgrades_either_existing_history(starting_revision: str) -> None:
    down = _alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr
    prior = _alembic("upgrade", starting_revision)
    assert prior.returncode == 0, prior.stderr
    user_id = uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, is_active, is_app_admin) "
                    "VALUES (:id, 'merge-upgrade@example.com', true, false)"
                ),
                {"id": user_id},
            )
        upgraded = _alembic("upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT email FROM users WHERE id = :id"), {"id": user_id}
                ).scalar_one()
                == "merge-upgrade@example.com"
            )
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
            )
        check = _alembic("check")
        assert check.returncode == 0, check.stderr
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", ["notifications", "notification_preferences"])
def test_eval_upgrade_preserves_existing_main_notification_rows(table: str) -> None:
    """Intermediate eval checks must accept populated, already deployed main events."""
    down = _alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr
    prior = _alembic("upgrade", "0303_merge_workflow_onboarding")
    assert prior.returncode == 0, prior.stderr
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.begin() as connection:
            user_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO users (id, email, is_active, is_app_admin) "
                    "VALUES (:id, 'notification-upgrade@example.com', true, false)"
                ),
                {"id": user_id},
            )
            definition = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = to_regclass(:table) AND contype = 'c' "
                    "AND pg_get_constraintdef(oid) LIKE '%event_type%'"
                ),
                {"table": table},
            ).scalar_one()
            events = set(re.findall(r"'([^']+)'", definition))
            assert {"capability_requested", "suggestion", "finding"} <= events
            if table == "notifications":
                insert = text(
                    "INSERT INTO notifications "
                    "(id, recipient_user_id, event_type, occurrence_id, summary, in_app_visible) "
                    "VALUES (:id, :user, :event, :event, 'Retain this notification', true)"
                )
            else:
                insert = text(
                    "INSERT INTO notification_preferences "
                    "(id, user_id, event_type, channel, enabled) "
                    "VALUES (:id, :user, :event, 'in_app', false)"
                )
            connection.execute(
                insert,
                [{"id": uuid4(), "user": user_id, "event": event} for event in sorted(events)],
            )
            snapshot = text(
                "SELECT row_to_json(t)::text FROM notifications t ORDER BY id"
                if table == "notifications"
                else "SELECT row_to_json(t)::text FROM notification_preferences t ORDER BY id"
            )
            before = connection.execute(snapshot).scalars().all()
        upgraded = _alembic("upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with engine.connect() as connection:
            assert connection.execute(snapshot).scalars().all() == before
        checked = _alembic("check")
        assert checked.returncode == 0, checked.stderr
    finally:
        engine.dispose()


class TestBotTranscriptionSwitch:
    """`0151_bot_transcription_switch.py`: no bot starts transcribing on upgrade.

    A bot with no pair used to be a bot that did not transcribe, and a new bot
    with no pair inherits one. The backfill is what keeps the first from turning
    into the second underneath its operator - the acceptance criterion "a bot
    that had no pair before the migration still does not transcribe" (#1797).
    """

    def test_a_pairless_bot_is_switched_off_and_a_paired_one_keeps_its_pair(self):
        assert _alembic("downgrade", "base").returncode == 0
        up = _alembic("upgrade", "0150_org_speech_settings")
        assert up.returncode == 0, up.stderr

        org = "00000000-0000-0000-0000-0000000000a1"
        bots = {
            "paired": ("00000000-0000-0000-0000-0000000000b1", "openai", "whisper-1"),
            "pairless": ("00000000-0000-0000-0000-0000000000b2", None, None),
            "half": ("00000000-0000-0000-0000-0000000000b3", "openai", None),
        }
        engine = create_engine(_url(MIGRATION_DATABASE))
        try:
            with engine.begin() as connection:
                # Rows written the way 0106's schema allowed, so the creator need
                # not exist: replica mode skips the foreign-key triggers.
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO organizations (id, name, slug, is_personal, "
                        "created_by_user_id) VALUES (:id, 'Acme', 'acme', false, :id)"
                    ),
                    {"id": org},
                )
                for bot_id, provider, model in bots.values():
                    connection.execute(
                        text(
                            "INSERT INTO channel_bots (id, organization_id, platform, name, "
                            "token_encrypted, secret_key_version, is_active, webhook_mode, "
                            "access_policy, speech_to_text_provider, speech_to_text_model) "
                            "VALUES (:id, :org, 'telegram', 'bot', 'x', 1, true, false, '{}', "
                            ":provider, :model)"
                        ),
                        {"id": bot_id, "org": org, "provider": provider, "model": model},
                    )

            up = _alembic("upgrade", "0151_bot_transcription_switch")
            assert up.returncode == 0, up.stderr

            with engine.connect() as connection:
                rows = {
                    str(row[0]): (row[1], row[2], row[3])
                    for row in connection.execute(
                        text(
                            "SELECT id, transcribe_voice_notes, speech_to_text_provider, "
                            "speech_to_text_model FROM channel_bots"
                        )
                    )
                }
        finally:
            engine.dispose()

        assert rows[bots["paired"][0]] == (True, "openai", "whisper-1")
        assert rows[bots["pairless"][0]] == (False, None, None)
        # Half a pair could not transcribe either, and the CHECK now refuses one.
        assert rows[bots["half"][0]] == (False, None, None)

        down = _alembic("downgrade", "0150_org_speech_settings")
        assert down.returncode == 0, down.stderr

    def test_a_paired_bot_is_given_the_key_its_profile_lookup_would_have_found(self):
        """The profile lookup is gone, so 0107 writes down the key it would have
        used - the first keyed profile by label for the bot's provider, with no
        address of its own - but only a key a bot may now be saved with: an
        organization-visible API key for that provider. Anything else leaves
        the key null, which the form shows as "choose a key"."""
        assert _alembic("downgrade", "base").returncode == 0
        up = _alembic("upgrade", "0150_org_speech_settings")
        assert up.returncode == 0, up.stderr

        org, other_org = (
            "00000000-0000-0000-0000-0000000000a1",
            "00000000-0000-0000-0000-0000000000a2",
        )
        owner = "00000000-0000-0000-0000-0000000000c1"
        secrets = {
            # Each is its id, then its organization, purpose, kind and visibility.
            "proxy": ("00000000-0000-0000-0000-0000000000d1", org, "openai", "api_key", "org"),
            "real": ("00000000-0000-0000-0000-0000000000d2", org, "openai", "api_key", "org"),
            "later": ("00000000-0000-0000-0000-0000000000d3", org, "openai", "api_key", "org"),
            "private": ("00000000-0000-0000-0000-0000000000d4", org, "groq", "api_key", "private"),
            "custom": ("00000000-0000-0000-0000-0000000000d5", org, "custom", "api_key", "org"),
        }
        profiles = [
            # Each is a label, a provider, the secret it names and its own address.
            ("a proxy", "openai", "proxy", "http://litellm.local/v1"),
            ("b real", "openai", "real", None),
            ("c later", "openai", "later", None),
            ("d groq", "groq", "private", None),
            ("e mistral", "mistral", "custom", None),
        ]
        bots = {
            "openai": ("00000000-0000-0000-0000-0000000000b1", org, "openai", "whisper-1"),
            "groq": ("00000000-0000-0000-0000-0000000000b2", org, "groq", "whisper-large-v3"),
            "mistral": (
                "00000000-0000-0000-0000-0000000000b3",
                org,
                "mistral",
                "voxtral-mini-latest",
            ),
            "elsewhere": ("00000000-0000-0000-0000-0000000000b4", other_org, "openai", "whisper-1"),
            "pairless": ("00000000-0000-0000-0000-0000000000b5", org, None, None),
        }
        engine = create_engine(_url(MIGRATION_DATABASE))
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                for org_id, slug in ((org, "acme"), (other_org, "other")):
                    connection.execute(
                        text(
                            "INSERT INTO organizations (id, name, slug, is_personal, "
                            "created_by_user_id) VALUES (:id, :slug, :slug, false, :id)"
                        ),
                        {"id": org_id, "slug": slug},
                    )
                for name, (secret_id, org_id, purpose, kind, visibility) in secrets.items():
                    connection.execute(
                        text(
                            "INSERT INTO organization_secrets (id, organization_id, name, kind, "
                            "purpose, visibility, owner_user_id, sealed_secret, hint, "
                            "key_version) VALUES (:id, :org, :name, :kind, :purpose, "
                            ":visibility, :owner, 'sealed', 'abcd', 1)"
                        ),
                        {
                            "id": secret_id,
                            "org": org_id,
                            "name": name,
                            "kind": kind,
                            "purpose": purpose,
                            "visibility": visibility,
                            "owner": owner,
                        },
                    )
                for label, provider, secret, base_url in profiles:
                    connection.execute(
                        text(
                            "INSERT INTO model_profiles (id, organization_id, label, provider, "
                            "model, secret_id, base_url) VALUES (gen_random_uuid(), "
                            ":org, :label, :provider, 'x', :secret, :base_url)"
                        ),
                        {
                            "org": org,
                            "label": label,
                            "provider": provider,
                            "secret": secrets[secret][0],
                            "base_url": base_url,
                        },
                    )
                for bot_id, org_id, provider, model in bots.values():
                    connection.execute(
                        text(
                            "INSERT INTO channel_bots (id, organization_id, platform, name, "
                            "token_encrypted, secret_key_version, is_active, webhook_mode, "
                            "access_policy, speech_to_text_provider, speech_to_text_model) "
                            "VALUES (:id, :org, 'telegram', 'bot', 'x', 1, true, false, '{}', "
                            ":provider, :model)"
                        ),
                        {"id": bot_id, "org": org_id, "provider": provider, "model": model},
                    )

            up = _alembic("upgrade", "0151_bot_transcription_switch")
            assert up.returncode == 0, up.stderr

            with engine.connect() as connection:
                keys = {
                    str(row[0]): None if row[1] is None else str(row[1])
                    for row in connection.execute(
                        text("SELECT id, speech_to_text_secret_id FROM channel_bots")
                    )
                }
        finally:
            engine.dispose()

        # The first by label with no address of its own - not the proxy, which
        # sorts first, and not the one after it.
        assert keys[bots["openai"][0]] == secrets["real"][0]
        # A member's private key is never spent for everybody's voice notes.
        assert keys[bots["groq"][0]] is None
        # A key stored for another purpose is not this provider's.
        assert keys[bots["mistral"][0]] is None
        # Another organization's profiles are not this bot's.
        assert keys[bots["elsewhere"][0]] is None
        assert keys[bots["pairless"][0]] is None

        down = _alembic("downgrade", "0150_org_speech_settings")
        assert down.returncode == 0, down.stderr


class TestReviewQueueKey:
    """`0174_case_score_agent_key.py`: a score keeps the agent that answered, and
    at most one score of a case waits for review for each agent."""

    def test_each_agent_keeps_one_waiting_score_of_a_case_and_the_rest_leave(self):
        assert _alembic("downgrade", "base").returncode == 0
        up = _alembic("upgrade", "0178_eval_run_proposal_check")
        assert up.returncode == 0, up.stderr

        org, dataset, case, revision = (
            "00000000-0000-0000-0000-0000000000a1",
            "00000000-0000-0000-0000-0000000000d1",
            "00000000-0000-0000-0000-0000000000c1",
            "00000000-0000-0000-0000-0000000000c2",
        )
        first, second = (
            "00000000-0000-0000-0000-0000000000e1",
            "00000000-0000-0000-0000-0000000000e2",
        )
        runs = {
            "first": ("00000000-0000-0000-0000-0000000000f1", first),
            "second": ("00000000-0000-0000-0000-0000000000f2", second),
        }
        eval_run = "00000000-0000-0000-0000-0000000000b1"
        # (run, eval run, passed, review state, minutes after the first score)
        scores = {
            "older fail": ("first", None, False, "pending", 0),
            "newer fail": ("first", None, False, "pending", 1),
            "judge error": (None, eval_run, None, "pending", 2),
            "decided": ("first", None, True, "done", 3),
            "other agent": ("second", None, None, "pending", 0),
            "no agent": (None, None, False, "pending", 0),
        }
        ids = {name: f"00000000-0000-0000-0000-{n:012d}" for n, name in enumerate(scores, 1)}
        engine = create_engine(_url(MIGRATION_DATABASE))
        try:
            with engine.begin() as connection:
                # Replica mode skips the foreign-key triggers, so the agents,
                # the dataset and its version need not exist.
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                for run_id, agent_id in runs.values():
                    connection.execute(
                        text(
                            "INSERT INTO agent_runs (id, organization_id, agent_id, surface, "
                            "status, input_tokens, output_tokens, cost_usd, cost_is_partial) "
                            "VALUES (:id, :org, :agent, 'api', 'completed', 0, 0, 0, false)"
                        ),
                        {"id": run_id, "org": org, "agent": agent_id},
                    )
                connection.execute(
                    text(
                        "INSERT INTO eval_runs (id, organization_id, agent_id, dataset_id, "
                        "dataset_version_id, status, purpose, paired, from_recordings, "
                        "live_reads, reruns, scoring, scoring_hash, estimate_usd, "
                        "rerun_ceiling_usd, routed_to_review, routed_replacing) VALUES "
                        "(:id, :org, :agent, :dataset, :dataset, 'completed', 'manual', false, "
                        "false, false, 0, '{}', 'x', 0, 0, 0, 0)"
                    ),
                    {"id": eval_run, "org": org, "agent": first, "dataset": dataset},
                )
                for name, (run, evaluated, passed, state, minutes) in scores.items():
                    connection.execute(
                        text(
                            "INSERT INTO case_scores (id, organization_id, dataset_id, "
                            "case_revision_id, case_id, run_id, eval_run_id, scoring, results, "
                            "passed, review_state, created_at) VALUES (:id, :org, :dataset, "
                            ":revision, :case, :run, :eval_run, '{}', '[]', :passed, :state, "
                            "TIMESTAMPTZ '2026-10-01 12:00+00' + make_interval(mins => :minutes))"
                        ),
                        {
                            "id": ids[name],
                            "org": org,
                            "dataset": dataset,
                            "revision": revision,
                            "case": case,
                            "run": None if run is None else runs[run][0],
                            "eval_run": evaluated,
                            "passed": passed,
                            "state": state,
                            "minutes": minutes,
                        },
                    )

            up = _alembic("upgrade", "0174_case_score_agent_key")
            assert up.returncode == 0, up.stderr

            with engine.connect() as connection:
                rows = {
                    str(row[0]): (None if row[1] is None else str(row[1]), row[2])
                    for row in connection.execute(
                        text("SELECT id, agent_id, review_state FROM case_scores")
                    )
                }
        finally:
            engine.dispose()

        assert {name: rows[ids[name]] for name in scores} == {
            "older fail": (first, "none"),
            "newer fail": (first, "pending"),
            "judge error": (first, "none"),
            "decided": (first, "done"),
            "other agent": (second, "pending"),
            "no agent": (None, "pending"),
        }
        assert "2 duplicate scores waiting for review left the queue undecided" in up.stderr

        down = _alembic("downgrade", "0178_eval_run_proposal_check")
        assert down.returncode == 0, down.stderr


@pytest.mark.parametrize("table", ["notifications", "notification_preferences"])
def test_workflow_migrations_preserve_main_notification_types(table: str) -> None:
    """Workflow CHECK rebuilds must retain the event types already deployed on main."""
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as connection:
            definition = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = to_regclass(:table) AND contype = 'c' "
                    "AND pg_get_constraintdef(oid) LIKE '%event_type%'"
                ),
                {"table": table},
            ).scalar_one()
        for event in (
            "capability_requested",
            "suggestion",
            "finding",
            "workflow_notification",
            "artifact_owner_changed",
            "artifact_share_requested",
            "workflow_log_alert",
        ):
            assert f"'{event}'" in definition
    finally:
        engine.dispose()


def test_workflow_child_cost_migration_rolls_up_each_charge_once() -> None:
    """Backfill explicit nested calls, preserving own spend and excluding trigger chains."""
    import uuid
    from datetime import UTC, datetime
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from app.db.models.organization import Organization
    from app.db.models.user import User
    from app.db.models.workflow import Workflow
    from app.db.models.workflow_run import NodeRun, WorkflowRun

    upgraded = _alembic("upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with Session(engine) as db:
            owner = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
            db.add(owner)
            db.flush()
            org = Organization(
                name="Costs", slug=f"costs-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
            )
            db.add(org)
            db.flush()
            workflow = Workflow(
                organization_id=org.id,
                owner_user_id=owner.id,
                name="Calls",
                slug=f"calls-{uuid.uuid4().hex[:8]}",
                draft_graph={},
            )
            db.add(workflow)
            db.flush()
            runs: list[WorkflowRun] = []
            steps: list[NodeRun] = []
            for amount in range(1, 5):
                run_id = uuid.uuid4()
                run = WorkflowRun(
                    id=run_id,
                    organization_id=org.id,
                    workflow_id=workflow.id,
                    mode="test",
                    draft_graph_snapshot={},
                    status="succeeded",
                    triggered_by="api",
                    execution_principal_user_id=owner.id,
                    root_run_id=run_id,
                    node_count=1,
                    spent_cost=Decimal(amount),
                    cost_is_partial=amount == 3,
                    started_at=datetime.now(UTC),
                )
                db.add(run)
                db.flush()
                step = NodeRun(
                    organization_id=org.id,
                    workflow_run_id=run.id,
                    node_instance_id=uuid.uuid4(),
                    scope_path=[],
                    status="succeeded",
                )
                db.add(step)
                db.flush()
                runs.append(run)
                steps.append(step)
            runs[1].parent_node_run_id = steps[0].id
            runs[2].parent_node_run_id = steps[1].id
            # A trigger can share the root without being a called workflow.
            runs[3].root_run_id = runs[0].id
            ids = [run.id for run in runs]
            db.commit()
        down = _alembic("downgrade", "0225_workflow_api_key_authority")
        assert down.returncode == 0, down.stderr
        again = _alembic("upgrade", "head")
        assert again.returncode == 0, again.stderr
        with engine.connect() as connection:
            rows = [
                connection.execute(
                    text(
                        "SELECT spent_cost, child_cost, cost_is_partial FROM workflow_runs WHERE id = :id"
                    ),
                    {"id": run_id},
                ).one()
                for run_id in ids
            ]
        assert [(row.spent_cost, row.child_cost) for row in rows] == [
            (Decimal(1), Decimal(5)),
            (Decimal(2), Decimal(3)),
            (Decimal(3), Decimal(0)),
            (Decimal(4), Decimal(0)),
        ]
        assert [row.cost_is_partial for row in rows] == [True, True, True, False]
    finally:
        engine.dispose()


class TestLegacyCookieSessionRevocation:
    @pytest.mark.anyio
    @pytest.mark.security
    async def test_upgrade_revokes_old_refresh_chains_without_restoring_them_on_downgrade(self):
        reset = _alembic("downgrade", "base")
        assert reset.returncode == 0, reset.stderr
        up = _alembic("upgrade", "0172_mcp_health_queue_clock")
        assert up.returncode == 0, up.stderr
        engine = create_async_engine(
            f"{settings.DATABASE_URL.rsplit('/', 1)[0]}/{MIGRATION_DATABASE}"
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as db:
                user = User(email=f"cookie-migration-{uuid4()}@example.com")
                admin = User(email=f"cookie-admin-{uuid4()}@example.com")
                db.add_all([user, admin])
                await db.flush()
                now = datetime.now(UTC)
                old_id, impersonation_id, ended_id, user_id = uuid4(), uuid4(), uuid4(), user.id
                # Seed the historical schema without today's app/push columns.
                await db.execute(
                    text(
                        "INSERT INTO sessions (id, user_id, impersonator_user_id, refresh_token_hash, previous_refresh_token_hash, rotated_at, expires_at, is_active, created_at, last_used_at) VALUES (:id, :user, :impersonator, :current, :previous, :rotated, :expires, :active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    [
                        {
                            "id": old_id,
                            "user": user.id,
                            "impersonator": None,
                            "current": hash_token("legacy-current"),
                            "previous": hash_token("legacy-spent"),
                            "rotated": now,
                            "expires": now + timedelta(days=1),
                            "active": True,
                        },
                        {
                            "id": impersonation_id,
                            "user": user.id,
                            "impersonator": admin.id,
                            "current": hash_token("legacy-impersonation"),
                            "previous": None,
                            "rotated": None,
                            "expires": now + timedelta(minutes=5),
                            "active": True,
                        },
                        {
                            "id": ended_id,
                            "user": user.id,
                            "impersonator": None,
                            "current": hash_token("legacy-ended"),
                            "previous": None,
                            "rotated": None,
                            "expires": now + timedelta(days=1),
                            "active": False,
                        },
                    ],
                )
                await db.commit()
                assert (
                    await db.scalar(
                        text("SELECT is_active FROM sessions WHERE id=:id"), {"id": old_id}
                    )
                    is True
                )
                await db.commit()

            up = _alembic("upgrade", "0173_revoke_cookie_sessions")
            assert up.returncode == 0, up.stderr
            async with factory() as db:
                active = (
                    (
                        await db.execute(
                            text(
                                "SELECT is_active FROM sessions WHERE id IN (:old, :impersonation, :ended)"
                            ),
                            {"old": old_id, "impersonation": impersonation_id, "ended": ended_id},
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(active) == 3 and not any(active)
            # Current services are exercised only once their full schema exists.
            up = _alembic("upgrade", "head")
            assert up.returncode == 0, up.stderr
            async with factory() as db:
                service = SessionService(db)
                current = await service.validate_refresh_token("legacy-current")
                previous = await service.claim_refresh_grace("legacy-spent")
                assert current is None
                assert previous is None
                with pytest.raises(AuthenticationError, match="Session has ended"):
                    await service.verify_access_session(
                        payload={"sid": str(old_id)}, subject=str(user_id)
                    )
                rows = list(
                    await db.scalars(
                        select(Session).where(Session.id.in_([old_id, impersonation_id, ended_id]))
                    )
                )
                assert len(rows) == 3
                assert all(not row.is_active for row in rows)
                fresh = Session(
                    user_id=user_id,
                    refresh_token_hash=hash_token("fresh-current"),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                    is_active=True,
                )
                db.add(fresh)
                await db.commit()
                fresh_id = fresh.id
                refreshed = await service.validate_refresh_token("fresh-current")
                assert refreshed is fresh
                await service.verify_access_session(
                    payload={"sid": str(fresh_id)}, subject=str(user_id)
                )
                await db.commit()

            down = _alembic("downgrade", "0172_mcp_health_queue_clock")
            assert down.returncode == 0, down.stderr
            async with factory() as db:
                revoked = await db.scalar(
                    text("SELECT is_active FROM sessions WHERE id=:id"), {"id": old_id}
                )
                retained = await db.scalar(
                    text("SELECT is_active FROM sessions WHERE id=:id"), {"id": fresh_id}
                )
                assert revoked is False
                assert retained is True
        finally:
            await engine.dispose()


class TestMessageClientCorrelation:
    def test_old_messages_survive_upgrade_downgrade_and_the_models_match_head(self):
        reset = _alembic("downgrade", "base")
        assert reset.returncode == 0, reset.stderr
        up = _alembic("upgrade", "0173_revoke_cookie_sessions")
        assert up.returncode == 0, up.stderr
        engine = create_engine(_url(MIGRATION_DATABASE))
        message_id = uuid4()
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content) VALUES (:id, :conversation, 'user', 'before correlation')"
                    ),
                    {"id": message_id, "conversation": uuid4()},
                )
            up = _alembic("upgrade", "head")
            assert up.returncode == 0, up.stderr
            with engine.connect() as connection:
                row = connection.execute(
                    text("SELECT content, client_message_id FROM messages WHERE id=:id"),
                    {"id": message_id},
                ).one()
                assert tuple(row) == ("before correlation", None)
            check = _alembic("check")
            assert check.returncode == 0, check.stderr
            down = _alembic("downgrade", "0173_revoke_cookie_sessions")
            assert down.returncode == 0, down.stderr
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        text("SELECT content FROM messages WHERE id=:id"), {"id": message_id}
                    )
                    == "before correlation"
                )
        finally:
            engine.dispose()


class TestChatNoticeColumn:
    def test_parked_runs_survive_upgrade_and_downgrade_and_the_models_match_head(self):
        reset = _alembic("downgrade", "base")
        assert reset.returncode == 0, reset.stderr
        up = _alembic("upgrade", "0254_model_profile_region")
        assert up.returncode == 0, up.stderr
        engine = create_engine(_url(MIGRATION_DATABASE))
        run_id = uuid4()
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO agent_runs (id, organization_id, agent_id, status, surface, modality, "
                        "started_at, input_tokens, output_tokens, cache_read_tokens, "
                        "cache_write_tokens, cost_usd, cost_is_partial, tool_args_repaired) "
                        "VALUES (:id, :org, :agent, 'awaiting_approval', 'slack', 'text', now(), "
                        "0, 0, 0, 0, 0, false, 0)"
                    ),
                    {"id": run_id, "org": uuid4(), "agent": uuid4()},
                )
            up = _alembic("upgrade", "head")
            assert up.returncode == 0, up.stderr
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        text("SELECT chat_notice_sent_at FROM agent_runs WHERE id=:id"),
                        {"id": run_id},
                    )
                    is None
                )
            check = _alembic("check")
            assert check.returncode == 0, check.stderr
            down = _alembic("downgrade", "0254_model_profile_region")
            assert down.returncode == 0, down.stderr
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        text("SELECT status FROM agent_runs WHERE id=:id"), {"id": run_id}
                    )
                    == "awaiting_approval"
                )
                assert not connection.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name='agent_runs' AND column_name='chat_notice_sent_at'"
                    )
                ).first()
        finally:
            engine.dispose()


class TestChannelRatingAuthors:
    def test_account_votes_survive_and_channel_authors_are_constrained(self):
        reset = _alembic("downgrade", "base")
        assert reset.returncode == 0, reset.stderr
        before = _alembic("upgrade", "0174_message_client_id")
        assert before.returncode == 0, before.stderr
        engine = create_engine(_url(MIGRATION_DATABASE))
        message_id, user_id, original_id, identity_id = (uuid4() for _ in range(4))
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO message_ratings (id, message_id, user_id, rating) VALUES (:id, :message, :user, 1)"
                    ),
                    {"id": original_id, "message": message_id, "user": user_id},
                )
            upgraded = _alembic("upgrade", "head")
            assert upgraded.returncode == 0, upgraded.stderr
            with engine.begin() as connection:
                row = connection.execute(
                    text("SELECT user_id, channel_identity_id FROM message_ratings WHERE id=:id"),
                    {"id": original_id},
                ).one()
                assert tuple(row) == (user_id, None)
                connection.execute(
                    text(
                        "INSERT INTO channel_identities (id, platform, platform_user_id, is_active) VALUES (:id, 'mattermost', 'participant', true)"
                    ),
                    {"id": identity_id},
                )
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO message_ratings (id, message_id, channel_identity_id, rating) VALUES (:id, :message, :identity, -1)"
                    ),
                    {"id": uuid4(), "message": message_id, "identity": identity_id},
                )
            from sqlalchemy.exc import IntegrityError

            for user, identity in [(None, None), (user_id, identity_id)]:
                with pytest.raises(IntegrityError), engine.begin() as connection:
                    connection.execute(text("SET LOCAL session_replication_role = replica"))
                    connection.execute(
                        text(
                            "INSERT INTO message_ratings (id, message_id, user_id, channel_identity_id, rating) VALUES (:id, :message, :user, :identity, 1)"
                        ),
                        {"id": uuid4(), "message": uuid4(), "user": user, "identity": identity},
                    )
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO message_ratings (id, message_id, channel_identity_id, rating) VALUES (:id, :message, :identity, 1)"
                    ),
                    {"id": uuid4(), "message": message_id, "identity": identity_id},
                )
            back = _alembic("downgrade", "0174_message_client_id")
            assert back.returncode == 0, back.stderr
            with engine.connect() as connection:
                assert connection.execute(
                    text("SELECT id, user_id FROM message_ratings")
                ).all() == [(original_id, user_id)]
            restored = _alembic("upgrade", "head")
            assert restored.returncode == 0, restored.stderr
            check = _alembic("check")
            assert check.returncode == 0, check.stderr + check.stdout
        finally:
            engine.dispose()


class TestSkillBindingAvailability:
    def test_removing_the_switch_preserves_skills_and_rolls_back_on_populated_tables(self):
        reset = _alembic("downgrade", "base")
        assert reset.returncode == 0, reset.stderr
        before = _alembic("upgrade", "0179_session_push_preferences")
        assert before.returncode == 0, before.stderr
        engine = create_engine(_url(MIGRATION_DATABASE))
        skill_ids = [uuid4(), uuid4()]
        selected = {"a": skill_ids[0], "b": skill_ids[1]}
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                for index, skill_id in enumerate(skill_ids):
                    connection.execute(
                        text(
                            "INSERT INTO skills (id, organization_id, name, description, content, "
                            "enabled, version, visibility) VALUES "
                            "(:id, :org, :name, 'A procedure', 'Check the order', :enabled, 1, 'org')"
                        ),
                        {
                            "id": skill_id,
                            "org": uuid4(),
                            "name": f"procedure-{index}",
                            "enabled": bool(index),
                        },
                    )
            upgraded = _alembic("upgrade", "0180_remove_skill_enabled")
            assert upgraded.returncode == 0, upgraded.stderr
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM skills WHERE id IN (:a, :b)"), selected
                    ).scalar_one()
                    == 2
                )
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'skills' AND column_name = 'enabled'"
                        )
                    ).scalar_one()
                    == 0
                )
            downgraded = _alembic("downgrade", "0179_session_push_preferences")
            assert downgraded.returncode == 0, downgraded.stderr
            with engine.connect() as connection:
                assert connection.execute(
                    text("SELECT enabled FROM skills WHERE id IN (:a, :b)"), selected
                ).scalars().all() == [True, True]
            upgraded_again = _alembic("upgrade", "0180_remove_skill_enabled")
            assert upgraded_again.returncode == 0, upgraded_again.stderr
        finally:
            # Their organization was never written, so a later upgrade past 0250,
            # which gives every skill a version in its organization, would fail on them.
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM skills WHERE id IN (:a, :b)"), selected)
            engine.dispose()


class TestRunSkillUsesBackfill:
    def test_transcripts_become_uses_and_every_older_run_reads_unknown(self) -> None:
        """Loads and file reads are copied by skill, never to a skill named so later.

        The runs stay unrecorded - an old transcript proves a load, never the
        absence of one - while a run written after the upgrade is recorded.
        """
        reset = _alembic("downgrade", "base")
        assert reset.returncode == 0, reset.stderr
        before = _alembic("upgrade", "0306_shared_page_attribution")
        assert before.returncode == 0, before.stderr
        engine = create_engine(_url(MIGRATION_DATABASE))
        org, agent = uuid4(), uuid4()
        refunds, shipping, renamed = uuid4(), uuid4(), uuid4()
        loaded, quiet, later = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                # The parents a use points at; nothing else about them matters here.
                connection.execute(
                    text(
                        "INSERT INTO organizations (id, name, slug, is_personal, created_by_user_id) "
                        "VALUES (:id, 'Skills', :slug, false, :user)"
                    ),
                    {"id": org, "slug": f"skills-{org.hex[:8]}", "user": uuid4()},
                )
                connection.execute(
                    text(
                        "INSERT INTO agents (id, organization_id, visibility, slug, name, status) "
                        "VALUES (:id, :org, 'org', :slug, 'Refund desk', 'draft')"
                    ),
                    {"id": agent, "org": org, "slug": f"refunds-{agent.hex[:8]}"},
                )
                for skill_id, name, created in (
                    (refunds, "refunds", now - timedelta(days=10)),
                    (shipping, "shipping", now - timedelta(days=10)),
                    # Named like a skill a run loaded, and created after that run.
                    (renamed, "returns", now),
                ):
                    connection.execute(
                        text(
                            "INSERT INTO skills (id, organization_id, name, description, content, "
                            "version, visibility, created_at) VALUES "
                            "(:id, :org, :name, 'A procedure', 'Check', 1, 'org', :created)"
                        ),
                        {"id": skill_id, "org": org, "name": name, "created": created},
                    )
                calls = {
                    loaded: [
                        ("load_capability", {"id": "refunds"}, "completed"),
                        ("read_skill_resource", {"skill_name": "refunds"}, "completed"),
                        ("read_skill_resource", {"skill_name": "refunds"}, "completed"),
                        ("load_skill", {"skill_name": "shipping"}, "completed"),
                        ("load_capability", {"id": "returns"}, "completed"),
                        ("search_documents", {"query": "refunds"}, "completed"),
                    ],
                    # Calls that never ran opened nothing.
                    quiet: [
                        ("load_capability", {"id": "refunds"}, "failed"),
                        ("read_skill_resource", {"skill_name": "refunds"}, "awaiting_approval"),
                        ("read_skill_resource", {"skill_name": "refunds"}, "rejected"),
                    ],
                }
                for run_id, made in calls.items():
                    connection.execute(
                        text(
                            "INSERT INTO agent_runs (id, organization_id, agent_id, surface, status, "
                            "input_tokens, output_tokens, cost_usd, cost_is_partial, started_at) "
                            "VALUES (:id, :org, :agent, 'chat', 'completed', 0, 0, 0, false, :at)"
                        ),
                        {"id": run_id, "org": org, "agent": agent, "at": now - timedelta(days=5)},
                    )
                    message = uuid4()
                    connection.execute(
                        text(
                            "INSERT INTO messages (id, conversation_id, role, content, ordinal, run_id) "
                            "VALUES (:id, :conversation, 'assistant', 'Done', 1, :run)"
                        ),
                        {"id": message, "conversation": uuid4(), "run": run_id},
                    )
                    for index, (tool, args, status) in enumerate(made):
                        connection.execute(
                            text(
                                "INSERT INTO tool_calls (id, message_id, tool_call_id, tool_name, "
                                "args, status, started_at) VALUES "
                                "(:id, :message, :call, :tool, CAST(:args AS jsonb), :status, :at)"
                            ),
                            {
                                "id": uuid4(),
                                "message": message,
                                "call": f"c{index}",
                                "tool": tool,
                                "args": json.dumps(args),
                                "status": status,
                                "at": now,
                            },
                        )
            up = _alembic("upgrade", "0305_run_skill_uses")
            assert up.returncode == 0, up.stderr
            with engine.begin() as connection:
                uses = connection.execute(
                    text(
                        "SELECT run_id, agent_id, skill_id, loaded, resource_reads, workspace_reads, "
                        "skill_version_id FROM run_skill_uses WHERE organization_id = :org"
                    ),
                    {"org": org},
                ).all()
                assert sorted(
                    (use.skill_id, use.loaded, use.resource_reads) for use in uses
                ) == sorted([(refunds, True, 2), (shipping, True, 0)])
                assert {(use.run_id, use.agent_id) for use in uses} == {(loaded, agent)}
                assert {(use.workspace_reads, use.skill_version_id) for use in uses} == {(0, None)}
                assert connection.execute(
                    text("SELECT skill_uses_recorded FROM agent_runs WHERE id IN (:a, :b)"),
                    {"a": loaded, "b": quiet},
                ).scalars().all() == [False, False]
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO agent_runs (id, organization_id, agent_id, surface, status, "
                        "input_tokens, output_tokens, cost_usd, cost_is_partial) "
                        "VALUES (:id, :org, :agent, 'chat', 'completed', 0, 0, 0, false)"
                    ),
                    {"id": later, "org": org, "agent": agent},
                )
                assert (
                    connection.execute(
                        text("SELECT skill_uses_recorded FROM agent_runs WHERE id = :id"),
                        {"id": later},
                    ).scalar_one()
                    is True
                )
            back = _alembic("downgrade", "0306_shared_page_attribution")
            assert back.returncode == 0, back.stderr
            again = _alembic("upgrade", "head")
            assert again.returncode == 0, again.stderr
        finally:
            engine.dispose()


class TestDiscordMembershipSources:
    def test_discord_rows_survive_downgrade_as_manual_memberships(self):
        reset = _alembic("downgrade", "base")
        assert reset.returncode == 0, reset.stderr
        before = _alembic("upgrade", "0255_run_chat_notice_sent_at")
        assert before.returncode == 0, before.stderr
        engine = create_engine(_url(MIGRATION_DATABASE))
        member_id, group_member_id = uuid4(), uuid4()
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO organization_members (id, organization_id, user_id, role, source) VALUES (:id, :org, :user, 'member', 'directory')"
                    ),
                    {"id": member_id, "org": uuid4(), "user": uuid4()},
                )
                connection.execute(
                    text(
                        "INSERT INTO group_members (id, group_id, user_id, source) VALUES (:id, :group, :user, 'directory')"
                    ),
                    {"id": group_member_id, "group": uuid4(), "user": uuid4()},
                )
            upgraded = _alembic("upgrade", "0256_discord_role_mappings")
            assert upgraded.returncode == 0, upgraded.stderr
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE organization_members SET source = 'discord' WHERE id = :id"),
                    {"id": member_id},
                )
                connection.execute(
                    text("UPDATE group_members SET source = 'discord' WHERE id = :id"),
                    {"id": group_member_id},
                )
            downgraded = _alembic("downgrade", "0255_run_chat_notice_sent_at")
            assert downgraded.returncode == 0, downgraded.stderr
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT source FROM organization_members WHERE id = :id"),
                        {"id": member_id},
                    ).scalar_one()
                    == "manual"
                )
                assert (
                    connection.execute(
                        text("SELECT source FROM group_members WHERE id = :id"),
                        {"id": group_member_id},
                    ).scalar_one()
                    == "manual"
                )
            restored = _alembic("upgrade", "head")
            assert restored.returncode == 0, restored.stderr
        finally:
            engine.dispose()


class TestProactivityMainMerge:
    def test_existing_discord_exposure_survives_proactivity_upgrade_and_downgrade(self):
        reset = _alembic("downgrade", "base")
        assert reset.returncode == 0, reset.stderr
        before = _alembic("upgrade", "0256_discord_role_mappings")
        assert before.returncode == 0, before.stderr
        engine = create_engine(_url(MIGRATION_DATABASE))
        exposure_id = uuid4()
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO agent_exposures "
                        "(id, organization_id, agent_id, channel_bot_id, surface, is_active) "
                        "VALUES (:id, :org, :agent, :bot, 'discord', true)"
                    ),
                    {"id": exposure_id, "org": uuid4(), "agent": uuid4(), "bot": uuid4()},
                )
            up = _alembic("upgrade", "head")
            assert up.returncode == 0, up.stderr
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        text("SELECT surface FROM agent_exposures WHERE id=:id"),
                        {"id": exposure_id},
                    )
                    == "discord"
                )
            check = _alembic("check")
            assert check.returncode == 0, check.stderr
            down = _alembic("downgrade", "0256_discord_role_mappings")
            assert down.returncode == 0, down.stderr
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        text("SELECT surface FROM agent_exposures WHERE id=:id"),
                        {"id": exposure_id},
                    )
                    == "discord"
                )
            restored = _alembic("upgrade", "head")
            assert restored.returncode == 0, restored.stderr
        finally:
            engine.dispose()


class TestConnectedAccountMigration:
    def test_upgrade_and_downgrade_preserve_mcp_rows(self) -> None:
        before = _alembic("upgrade", "head")
        assert before.returncode == 0, before.stderr
        owner, server, account = uuid4(), uuid4(), uuid4()
        engine = create_engine(_url(MIGRATION_DATABASE))
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users (id, email, is_active, is_app_admin) VALUES (:id, :email, true, false)"
                    ),
                    {"id": owner, "email": f"{owner}@example.com"},
                )
                for connection_id, purpose in ((server, "mcp"), (account, "account")):
                    connection.execute(
                        text(
                            "INSERT INTO mcp_connections "
                            "(id, user_id, scope, purpose, name, url, secret_key_version, account_email, is_enabled, auth_type) "
                            "VALUES (:id, :user, 'user', :purpose, :name, 'https://example.com', 1, :email, true, 'oauth')"
                        ),
                        {
                            "id": connection_id,
                            "user": owner,
                            "purpose": purpose,
                            "name": f"connection-{connection_id}",
                            "email": "ana@example.com" if purpose == "account" else None,
                        },
                    )
            down = _alembic("downgrade", "0256_discord_role_mappings")
            assert down.returncode == 0, down.stderr
            with engine.connect() as connection:
                rows = connection.execute(
                    text("SELECT id, purpose FROM mcp_connections WHERE user_id = :user"),
                    {"user": owner},
                ).all()
                assert rows == [(server, "mcp")]
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM information_schema.columns "
                            "WHERE table_name = 'mcp_connections' AND column_name = 'account_email'"
                        )
                    ).scalar_one()
                    == 0
                )
            up = _alembic("upgrade", "0257_connected_accounts")
            assert up.returncode == 0, up.stderr
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM pg_indexes WHERE tablename = 'mcp_connections' "
                            "AND indexname IN ('uq_connected_accounts_user_email', 'uq_connected_accounts_org_email')"
                        )
                    ).scalar_one()
                    == 2
                )
        finally:
            engine.dispose()


class TestConnectedAccountSources:
    @pytest.mark.security
    def test_source_tenant_upgrade_and_downgrade_keep_mcp_connections(self) -> None:
        up = _alembic("upgrade", "head")
        assert up.returncode == 0, up.stderr
        engine = create_engine(_url(MIGRATION_DATABASE))
        try:
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'mcp_connections' AND column_name = 'account_source_organization_id'"
                        )
                    ).scalar_one()
                    == 1
                )
            down = _alembic("downgrade", "0292_merge_connected_accounts")
            assert down.returncode == 0, down.stderr
            again = _alembic("upgrade", "head")
            assert again.returncode == 0, again.stderr
        finally:
            engine.dispose()


class TestDraftPresentationMigration:
    @pytest.mark.security
    def test_backfill_uses_published_bindings_not_provider_result_markers(self) -> None:
        import json

        up = _alembic("upgrade", "head")
        assert up.returncode == 0, up.stderr
        down = _alembic("downgrade", "0293_connected_account_sources")
        assert down.returncode == 0, down.stderr
        engine = create_engine(_url(MIGRATION_DATABASE))
        version_id, message_id, real_id, spoof_id = (uuid4() for _ in range(4))
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
                connection.execute(
                    text(
                        "INSERT INTO agent_versions (id, agent_id, organization_id, version, spec) VALUES (:id,:agent,:org,1,CAST(:spec AS jsonb))"
                    ),
                    {
                        "id": version_id,
                        "agent": uuid4(),
                        "org": uuid4(),
                        "spec": json.dumps(
                            {
                                "capabilities": [
                                    {
                                        "id": "drafts",
                                        "tool_overrides": {"write_draft": {"name": "save_reply"}},
                                    }
                                ]
                            }
                        ),
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO messages (id,conversation_id,role,content,agent_version_id) VALUES (:id,:conversation,'assistant','',:version)"
                    ),
                    {"id": message_id, "conversation": uuid4(), "version": version_id},
                )
                for identifier, name in ((real_id, "save_reply"), (spoof_id, "external")):
                    connection.execute(
                        text(
                            "INSERT INTO tool_calls (id,message_id,tool_call_id,tool_name,args,result,status,started_at) VALUES (:id,:message,:call,:name,'{}','Drafted fake. [agenticos:draft:v1]','completed',now())"
                        ),
                        {
                            "id": identifier,
                            "message": message_id,
                            "call": str(identifier),
                            "name": name,
                        },
                    )
            again = _alembic("upgrade", "head")
            assert again.returncode == 0, again.stderr
            with engine.connect() as connection:
                rows = dict(
                    connection.execute(
                        text(
                            "SELECT id,presentation_kind FROM tool_calls WHERE id IN (:real,:spoof)"
                        ),
                        {"real": real_id, "spoof": spoof_id},
                    ).all()
                )
                assert rows == {real_id: "draft", spoof_id: None}
            check = _alembic("check")
            assert check.returncode == 0, check.stderr
        finally:
            engine.dispose()


def test_shared_attribution_defaults_and_opt_out_survive_upgrade() -> None:
    for action, revision in (("upgrade", "head"), ("downgrade", "0305_defer_delete_crosslinks")):
        result = _alembic(action, revision)
        assert result.returncode == 0, result.stderr
    engine = create_engine(_url(MIGRATION_DATABASE))
    user_id, existing_id, new_id = uuid4(), uuid4(), uuid4()
    insert_org = text(
        "INSERT INTO organizations (id, name, slug, is_personal, created_by_user_id) "
        "VALUES (:id, 'Attribution', :slug, false, :creator)"
    )
    preference = text("SELECT public_agenticos_attribution FROM organizations WHERE id = :id")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, is_active, is_app_admin) VALUES (:id, :email, true, false)"
                ),
                {"id": user_id, "email": f"{user_id}@example.com"},
            )
            connection.execute(
                insert_org, {"id": existing_id, "slug": str(existing_id), "creator": user_id}
            )
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        with engine.begin() as connection:
            assert connection.execute(preference, {"id": existing_id}).scalar_one() is True
            connection.execute(insert_org, {"id": new_id, "slug": str(new_id), "creator": user_id})
            assert connection.execute(preference, {"id": new_id}).scalar_one() is True
            connection.execute(
                text(
                    "UPDATE organizations SET public_agenticos_attribution = false WHERE id = :id"
                ),
                {"id": existing_id},
            )
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            assert connection.execute(preference, {"id": existing_id}).scalar_one() is False
            assert connection.execute(preference, {"id": new_id}).scalar_one() is True
        result = _alembic("downgrade", "0305_defer_delete_crosslinks")
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns WHERE table_name = 'organizations' AND column_name = 'public_agenticos_attribution'"
                    )
                ).scalar_one()
                == 0
            )
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        check = _alembic("check")
        assert check.returncode == 0, check.stderr
    finally:
        engine.dispose()


def test_a_call_still_waiting_that_always_asks_is_marked() -> None:
    """A call parked before the column existed never expires, so one that always asks is marked."""
    for action, revision in (("upgrade", "head"), ("downgrade", "0306_shared_page_attribution")):
        result = _alembic(action, revision)
        assert result.returncode == 0, result.stderr
    wide_claim, own_claim = uuid4(), uuid4()
    rows = {
        "waiting share": ("share_memory", "pending", {}),
        "decided share": ("share_memory", "approved", {}),
        "waiting email": ("send_email", "pending", {}),
        "waiting wide correction": ("correct_memory", "pending", {"claim_id": str(wide_claim)}),
        "waiting own correction": ("correct_memory", "pending", {"claim_id": str(own_claim)}),
        "waiting nonsense correction": ("correct_memory", "pending", {"claim_id": "not-an-id"}),
    }
    ids = {name: str(uuid4()) for name in rows}
    org, agent, run = uuid4(), uuid4(), uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.begin() as connection:
            # Replica mode skips the foreign-key triggers, so no organization,
            # agent or run has to exist for the approvals to name.
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            for claim_id, scope_key in (
                (wide_claim, f"org:{org}"),
                (own_claim, f"person:{uuid4()}"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO memory_claims (id, organization_id, scope_key, statement, "
                        "kind, origin, status) "
                        "VALUES (:id, :org, :scope, 'Office closes at six', 'fact', 'person', "
                        "'current')"
                    ),
                    {"id": claim_id, "org": org, "scope": scope_key},
                )
            for name, (tool, status, args) in rows.items():
                connection.execute(
                    text(
                        "INSERT INTO tool_approvals (id, organization_id, run_id, agent_id, "
                        "tool_id, capability_tool_id, status, tool_args) "
                        "VALUES (:id, :org, :run, :agent, :tool, :tool, :status, "
                        "CAST(:args AS jsonb))"
                    ),
                    {
                        "id": ids[name],
                        "org": org,
                        "run": run,
                        "agent": agent,
                        "tool": tool,
                        "status": status,
                        "args": json.dumps(args),
                    },
                )
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            marked = {
                name: connection.execute(
                    text("SELECT always_asks FROM tool_approvals WHERE id = :id"),
                    {"id": ids[name]},
                ).scalar_one()
                for name in rows
            }
        assert marked == {
            "waiting share": True,
            "decided share": False,
            "waiting email": False,
            "waiting wide correction": True,
            "waiting own correction": False,
            "waiting nonsense correction": False,
        }
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM tool_approvals WHERE id::text = ANY(:ids)"),
                {"ids": list(ids.values())},
            )
            connection.execute(
                text("DELETE FROM memory_claims WHERE id::text = ANY(:ids)"),
                {"ids": [str(wide_claim), str(own_claim)]},
            )
        engine.dispose()


def test_opensandbox_upgrade_and_guarded_downgrade_preserve_connection_settings() -> None:
    """Images widen without changing old connections, and rollback never drops live settings."""
    prior = _alembic("upgrade", "0316_trigger_attempts")
    assert prior.returncode == 0, prior.stderr
    engine = create_engine(_url(MIGRATION_DATABASE))
    owner, organization, legacy, remote = (uuid4() for _ in range(4))
    image = "registry.example/" + "a" * 150 + ":latest"
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, is_active, is_app_admin) VALUES (:id, :email, true, false)"
                ),
                {"id": owner, "email": f"{owner}@example.com"},
            )
            connection.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, is_personal, created_by_user_id) VALUES (:id, 'Sandbox migration', :slug, false, :owner)"
                ),
                {"id": organization, "slug": f"sandbox-{organization}", "owner": owner},
            )
            connection.execute(
                text(
                    "INSERT INTO sandbox_connections (id, organization_id, name, kind, default_runtime, is_default, is_active) VALUES (:id, :org, 'Legacy sandbox', 'docker', 'python', false, true)"
                ),
                {"id": legacy, "org": organization},
            )
        upgraded = _alembic("upgrade", "0317_opensandbox_connections")
        assert upgraded.returncode == 0, upgraded.stderr
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("SELECT secure_access FROM sandbox_connections WHERE id=:id"),
                    {"id": legacy},
                ).scalar_one()
                is False
            )
            connection.execute(
                text(
                    "INSERT INTO sandbox_connections (id, organization_id, name, kind, base_url, default_runtime, secure_access, is_default, is_active) VALUES (:id, :org, 'OpenSandbox', 'opensandbox', 'https://sandbox.example', :image, true, false, true)"
                ),
                {"id": remote, "org": organization, "image": image},
            )
        refused = _alembic("downgrade", "0316_trigger_attempts")
        assert refused.returncode != 0 and "Remove OpenSandbox connections" in refused.stderr
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT default_runtime, secure_access FROM sandbox_connections WHERE id=:id"),
                {"id": remote},
            ).one() == (image, True)
            connection.execute(text("DELETE FROM sandbox_connections WHERE id=:id"), {"id": remote})
            connection.execute(
                text("UPDATE sandbox_connections SET default_runtime=:image WHERE id=:id"),
                {"id": legacy, "image": image},
            )
        refused_long = _alembic("downgrade", "0316_trigger_attempts")
        assert refused_long.returncode != 0 and "64 characters" in refused_long.stderr
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE sandbox_connections SET default_runtime='python' WHERE id=:id"),
                {"id": legacy},
            )
        downgraded = _alembic("downgrade", "0316_trigger_attempts")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT character_maximum_length FROM information_schema.columns WHERE table_name='sandbox_connections' AND column_name='default_runtime'"
                    )
                ).scalar_one()
                == 64
            )
        restored = _alembic("upgrade", "head")
        assert restored.returncode == 0, restored.stderr
        drift = _alembic("check")
        assert drift.returncode == 0, drift.stderr
    finally:
        engine.dispose()
