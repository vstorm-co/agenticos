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

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
                old = Session(
                    user_id=user.id,
                    refresh_token_hash=hash_token("legacy-current"),
                    previous_refresh_token_hash=hash_token("legacy-spent"),
                    rotated_at=now,
                    expires_at=now + timedelta(days=1),
                    is_active=True,
                )
                impersonation = Session(
                    user_id=user.id,
                    impersonator_user_id=admin.id,
                    refresh_token_hash=hash_token("legacy-impersonation"),
                    expires_at=now + timedelta(minutes=5),
                    is_active=True,
                )
                ended = Session(
                    user_id=user.id,
                    refresh_token_hash=hash_token("legacy-ended"),
                    expires_at=now + timedelta(days=1),
                    is_active=False,
                )
                db.add_all([old, impersonation, ended])
                await db.commit()
                old_id, impersonation_id, ended_id, user_id = (
                    old.id,
                    impersonation.id,
                    ended.id,
                    user.id,
                )
                before = await SessionService(db).validate_refresh_token("legacy-current")
                assert before is old
                await db.commit()

            up = _alembic("upgrade", "0173_revoke_cookie_sessions")
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
                service = SessionService(db)
                revoked = await service.validate_refresh_token("legacy-current")
                retained = await service.validate_refresh_token("fresh-current")
                assert revoked is None
                assert retained is not None
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
