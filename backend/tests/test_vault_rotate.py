"""Tests for the `vault-rotate` sweep.

The command is the missing half of #8: `rewrap` existed with no production
caller, so the staged rotation the docs described had no implementation. What
matters here: a row's envelopes move together with their version column or not
at all, a failure names its row and does not stop the sweep, and a dry run
performs the full unwrap-and-rewrap without writing - so it proves every
stored envelope opens under today's keys before anything moves.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from app.commands import vault_rotate as sweep
from app.commands.vault_rotate import SEALED_TABLES, Report, _rotate_table, _run, vault_rotate
from app.core.config import settings
from app.core.vault import VaultScope, seal, unseal
from app.db.models.channel_bot import ChannelBot
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization_secret import OrganizationSecret

pytestmark = pytest.mark.anyio

KEY_A = "vault-master-key-a-" + "a" * 32
KEY_B = "vault-master-key-b-" + "b" * 32


def _spec(label: str) -> sweep.SealedTable:
    return next(spec for spec in SEALED_TABLES if spec.label == label)


def _db_returning(*row_lists):
    db = MagicMock()
    results = []
    for rows in row_lists:
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    return db


def _bot(org_id: uuid.UUID, **overrides) -> ChannelBot:
    defaults: dict = {
        "id": uuid.uuid4(),
        "organization_id": org_id,
        "platform": "telegram",
        "name": "bot",
        "token_encrypted": None,
        "webhook_secret_encrypted": None,
        "slack_signing_secret_encrypted": None,
        "slack_app_token_encrypted": None,
        "secret_key_version": 1,
    }
    return ChannelBot(**{**defaults, **overrides})


class TestRotateTable:
    async def test_a_rows_envelopes_move_together_with_its_version_column(self, monkeypatch):
        """Two sealed columns and the version column, written as one unit - the
        row property #552 exists to protect, held across a real key change."""
        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A})
        org_id = uuid.uuid4()
        scope = VaultScope.organization(org_id)
        bot = _bot(
            org_id,
            token_encrypted=seal("bot-token", scope=scope).ciphertext,
            webhook_secret_encrypted=seal("hook-secret", scope=scope).ciphertext,
        )

        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A, 2: KEY_B})
        report = Report()
        await _rotate_table(
            _db_returning([bot]), _spec("channel_bots"), target=2, dry_run=False, report=report
        )

        assert report.rotated == 1 and not report.failures
        assert bot.secret_key_version == 2
        assert unseal(bot.token_encrypted, scope=scope, key_version=2) == "bot-token"
        assert unseal(bot.webhook_secret_encrypted, scope=scope, key_version=2) == "hook-secret"

    async def test_a_dry_run_unwraps_and_rewraps_but_writes_nothing(self, monkeypatch):
        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A})
        org_id = uuid.uuid4()
        sealed = seal("bot-token", scope=VaultScope.organization(org_id)).ciphertext
        bot = _bot(org_id, token_encrypted=sealed)

        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A, 2: KEY_B})
        report = Report()
        await _rotate_table(
            _db_returning([bot]), _spec("channel_bots"), target=2, dry_run=True, report=report
        )

        assert report.rotated == 1
        assert bot.secret_key_version == 1
        assert bot.token_encrypted == sealed

    async def test_a_row_that_cannot_unwrap_is_reported_and_left_untouched(self, monkeypatch):
        """One unreadable row must not stop the sweep - stopping leaves an
        unknown remainder under the old key, where a report names the row."""
        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A, 2: KEY_B})
        org_id = uuid.uuid4()
        foreign = seal("stolen", scope=VaultScope.organization(uuid.uuid4()), key_version=1)
        ours = seal("bot-token", scope=VaultScope.organization(org_id), key_version=1)
        bad = _bot(org_id, token_encrypted=foreign.ciphertext)
        good = _bot(org_id, token_encrypted=ours.ciphertext)

        report = Report()
        await _rotate_table(
            _db_returning([bad, good]),
            _spec("channel_bots"),
            target=2,
            dry_run=False,
            report=report,
        )

        assert report.rotated == 1
        assert len(report.failures) == 1
        assert str(bad.id) in report.failures[0]
        assert bad.secret_key_version == 1 and bad.token_encrypted == foreign.ciphertext
        assert good.secret_key_version == 2

    async def test_a_row_with_no_envelope_is_counted_and_skipped(self):
        report = Report()
        await _rotate_table(
            _db_returning([_bot(uuid.uuid4())]),
            _spec("channel_bots"),
            target=1,
            dry_run=False,
            report=report,
        )
        assert report.no_secret == 1 and report.rotated == 0

    async def test_an_already_current_row_is_left_alone(self):
        org_id = uuid.uuid4()
        sealed = seal("bot-token", scope=VaultScope.organization(org_id)).ciphertext
        bot = _bot(org_id, token_encrypted=sealed)

        report = Report()
        await _rotate_table(
            _db_returning([bot]), _spec("channel_bots"), target=1, dry_run=False, report=report
        )

        assert report.current == 1 and report.rotated == 0
        assert bot.token_encrypted == sealed

    async def test_a_personal_connection_is_rewrapped_under_its_member(self, monkeypatch):
        """The one table whose scope is not the organization: a personal MCP
        connection belongs to its member, and rotating it under any org scope
        would write an envelope nobody can open."""
        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A})
        user_id = uuid.uuid4()
        scope = VaultScope.user(user_id)
        conn = McpConnection(
            id=uuid.uuid4(),
            user_id=user_id,
            organization_id=None,
            scope="user",
            name="github",
            url="https://example.com/mcp",
            auth_token=seal("ghp-token", scope=scope).ciphertext,
            oauth_payload=None,
            oauth_pending_payload=None,
            secret_key_version=1,
        )

        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A, 2: KEY_B})
        report = Report()
        await _rotate_table(
            _db_returning([conn]), _spec("mcp_connections"), target=2, dry_run=False, report=report
        )

        assert report.rotated == 1
        assert unseal(conn.auth_token, scope=scope, key_version=2) == "ghp-token"


class TestRun:
    @staticmethod
    def _db_context(db):
        @asynccontextmanager
        async def context():
            yield db

        return context

    async def test_it_walks_every_sealed_table_in_one_session(self, monkeypatch):
        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A, 2: KEY_B})
        org_id = uuid.uuid4()
        secret = OrganizationSecret(
            id=uuid.uuid4(),
            organization_id=org_id,
            name="openai",
            kind="api_key",
            purpose="custom",
            visibility="org",
            sealed_secret=seal(
                "sk-live-abcd", scope=VaultScope.organization(org_id), key_version=1
            ).ciphertext,
            hint="abcd",
            key_version=1,
        )
        db = _db_returning([secret], [], [], [], [])

        with patch.object(sweep, "get_db_context", self._db_context(db)):
            report = await _run(dry_run=False)

        assert db.execute.await_count == len(SEALED_TABLES)
        assert report.rotated == 1 and secret.key_version == 2


class TestEntryPoint:
    def test_it_reports_and_exits_zero_when_every_row_moved(self):
        with patch.object(sweep.asyncio, "run", return_value=Report(rotated=3, current=1)):
            result = CliRunner().invoke(vault_rotate, [])
        assert result.exit_code == 0
        assert "3 rows re-wrapped" in result.output

    def test_a_dry_run_says_so(self):
        with patch.object(sweep.asyncio, "run", return_value=Report(rotated=2)):
            result = CliRunner().invoke(vault_rotate, ["--dry-run"])
        assert result.exit_code == 0
        assert "would be re-wrapped (dry run)" in result.output

    def test_it_exits_non_zero_when_a_row_could_not_move(self):
        """A provisioning script must not read a partial rotation as done and
        drop the old key while rows still need it."""
        report = Report(rotated=1, failures=["channel_bots 123: Failed to unwrap"])
        with patch.object(sweep.asyncio, "run", return_value=report):
            result = CliRunner().invoke(vault_rotate, [])
        assert result.exit_code == 1
        assert "keep the old key" in result.output
