"""Tests for the `data-protection-report` command.

The report is evidence attached to a review, so the two things that matter are
that it says what the deployment actually configured and that it says nothing
else: no message text, no document, no secret value and no hint of one. The
tests below pin both, plus the one number a reviewer cannot re-derive by hand -
the count of files under `MEDIA_DIR` that no row points at any more.

`MEDIA_PATH_COLUMNS` gets a test of its own because it is the kind of list that
rots silently: a model that gains a media-path column and is missing from it
turns every file that column names into an apparent orphan, and the count stays
plausible while being wrong.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner
from sqlalchemy import inspect

from app.agents.capabilities import _registry as capability_registry
from app.commands import data_protection as report
from app.commands.data_protection import (
    CAPABILITIES_STAYING_INSIDE,
    MEDIA_PATH_COLUMNS,
    OUTBOUND_CAPABILITIES,
    Section,
    _capability_destinations,
    _collect,
    _collections,
    _credentials,
    _external_connections,
    _local_services,
    _model_destinations,
    _render,
    _retention,
    _settings_section,
    _tracing,
    _unreferenced_media,
    _walk_media,
    data_protection_report,
)
from app.core.config import settings
from app.db.base import Base

pytestmark = pytest.mark.anyio

MEDIA_COLUMN_NAMES = {"storage_path", "avatar_url", "logo_path", "favicon_path"}


def _result(rows: list[tuple]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    result.scalars.return_value.all.return_value = [row[0] for row in rows]
    return result


def _db(*row_lists: list[tuple], counts: list[int] | None = None) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_result(rows) for rows in row_lists])
    db.scalar = AsyncMock(side_effect=counts or [])
    return db


def _cells(section: Section) -> list[str]:
    return [str(cell) for row in section.rows for cell in row]


class TestWhatItReports:
    """Each section names the configuration that decides where data goes."""

    async def test_model_destinations_flag_plain_http_and_default_endpoints(self) -> None:
        db = _db(
            [
                ("City", "gateway", "openai", "gpt-5", "http://llm.internal"),
                ("City", "hosted", "anthropic", "claude-opus-5", None),
                ("City", "eu", "openai", "gpt-5", "https://eu.example/v1"),
            ]
        )

        section = await _model_destinations(db)

        assert [row[5] for row in section.rows] == ["plain HTTP", "", ""]
        assert section.rows[1][4] == "provider default"

    async def test_credentials_name_the_third_party_and_never_the_value(self) -> None:
        db = _db([("City", "llm", "api_key", "OpenAI production")], counts=[0] * 8)

        section = await _credentials(db)

        assert section.rows[0] == ["City", "llm", "api_key", "OpenAI production"]

    async def test_credentials_count_the_tables_that_seal_in_place(self) -> None:
        """A bot token is a sealed credential that has no organization_secrets row."""
        db = _db([], counts=[3] + [0] * 7)

        section = await _credentials(db)

        counted = {row[1].split(" (")[0]: row[3] for row in section.rows}
        assert counted["channel_bots"] == 3
        assert "organization_secrets" not in counted

    async def test_collections_report_an_off_site_parse_only_with_its_own_key(self) -> None:
        db = _db(
            [
                ("handbook", "openai", "text-embedding-3-small", None, {}),
                (
                    "tenders",
                    "ollama",
                    "nomic",
                    uuid.uuid4(),
                    {"pdf_parser": "llamaparse", "llamaparse_secret_id": str(uuid.uuid4())},
                ),
                ("drafts", "openai", "text-embedding-3-small", None, {"pdf_parser": "llamaparse"}),
            ]
        )

        section = await _collections(db)

        assert [row[4] for row in section.rows] == ["pymupdf", "llamaparse", "llamaparse"]
        assert [row[5] for row in section.rows] == ["no", "yes", "no"]
        assert [row[3] for row in section.rows] == ["provider API", "local service", "provider API"]

    async def test_local_services_label_a_deployment_wide_row(self) -> None:
        db = _db(
            [
                (None, "embedding", "ollama", "ollama-1", "http://ollama:11434", True),
                ("City", "ocr", "liteparse", "ocr-1", "http://ocr:8000", False),
            ]
        )

        section = await _local_services(db)

        assert [row[0] for row in section.rows] == ["deployment-wide", "City"]
        assert [row[5] for row in section.rows] == ["yes", "no"]

    async def test_external_connections_cover_mcp_sync_and_channels(self) -> None:
        db = _db(
            [("org", "linear", "https://mcp.linear.app/sse", "oauth")],
            [],
            [("gdrive", "Handbook drive", "handbook")],
            [("telegram", "city-bot", None)],
        )

        section = await _external_connections(db)

        assert [row[0] for row in section.rows] == ["MCP server", "Sync source", "Channel bot"]
        assert section.rows[0][1] == "org/linear"

    async def test_sync_source_without_a_collection_still_reports(self) -> None:
        db = _db([], [], [("s3", "Bucket", None)], [])

        section = await _external_connections(db)

        assert section.rows == [["Sync source", "Bucket", "s3", "-"]]

    async def test_a_portal_grant_is_not_reported_as_an_mcp_server(self) -> None:
        """A Gmail grant a trigger reads is not an address tool arguments reach."""
        db = _db([], [("org", "gmail", "gmail")], [], [])

        section = await _external_connections(db)

        assert section.rows == [["Trigger portal", "org/gmail", "gmail", "grant"]]

    async def test_a_query_string_is_redacted_because_it_can_be_the_credential(self) -> None:
        db = _db([("org", "hosted", "https://mcp.example/sse?key=live-token", "none")], [], [], [])

        section = await _external_connections(db)

        assert section.rows[0][2] == "https://mcp.example/sse?<redacted>"
        assert "live-token" not in str(section.rows)

    async def test_a_bot_with_no_server_of_its_own_reports_its_platform(self) -> None:
        db = _db([], [], [], [("slack", "city-bot", None)])

        section = await _external_connections(db)

        assert section.rows == [["Channel bot", "city-bot", "slack", "slack"]]

    async def test_a_sync_source_row_keeps_its_shape_when_a_url_has_no_query(self) -> None:
        db = _db([("org", "hosted", "https://mcp.example/sse", "none")], [], [], [])

        section = await _external_connections(db)

        assert section.rows[0][2] == "https://mcp.example/sse"

    async def test_a_self_hosted_bot_reports_the_server_it_posts_to(self) -> None:
        db = _db([], [], [], [("mattermost", "city-bot", "https://chat.city.example")])

        section = await _external_connections(db)

        assert section.rows == [
            ["Channel bot", "city-bot", "https://chat.city.example", "mattermost"]
        ]


class TestCapabilityDestinations:
    """A capability reaches an address no row in any other section names."""

    async def test_reports_an_outbound_capability_of_a_runnable_version(self) -> None:
        db = _db(
            [("research", 4, {"capabilities": [{"id": "web_research"}, {"id": "clock"}]})],
            [],
        )

        section = await _capability_destinations(db)

        assert len(section.rows) == 1
        assert section.rows[0][:3] == ["agent research", "default v4", "web_research"]
        assert "DuckDuckGo" in section.rows[0][3]

    async def test_reports_a_version_only_an_environment_pins(self) -> None:
        db = _db([], [("research", "production", 2, {"capabilities": [{"id": "web_fetch"}]})])

        section = await _capability_destinations(db)

        assert section.rows[0][1] == "environment production v2"

    def test_every_registered_capability_is_classified(self) -> None:
        """A new capability fails here rather than leaving the inventory short."""
        capability_registry.load_builtins()
        registered = {definition.id for definition in capability_registry.all_capabilities()}

        assert registered == set(OUTBOUND_CAPABILITIES) | CAPABILITIES_STAYING_INSIDE
        assert not set(OUTBOUND_CAPABILITIES) & CAPABILITIES_STAYING_INSIDE


class TestTracing:
    """What a span carries is per agent, and the report has to say which."""

    async def test_reports_the_deployment_token_the_content_mode_and_environments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LOGFIRE_TOKEN", "pylf_v1_eu_token")
        db = _db(
            [("support", "production")],
            [
                ("support", 3, {"observability": {"content": "none"}}),
                ("billing", 1, {"observability": {"token_secret_id": str(uuid.uuid4())}}),
                ("triage", 2, {}),
            ],
            [("support", "production", 3, {"observability": {"content": "none"}})],
        )

        section = await _tracing(db)

        assert section.rows[0][3] == "set"
        assert section.rows[1][3] == "content: none"
        assert section.rows[2][2] == "own project"
        assert section.rows[3][3] == "content: full"
        assert section.rows[4][:3] == ["agent support", "environment production v3", "own project"]

    async def test_an_environment_is_read_off_the_version_it_pins(self) -> None:
        """A pinned version exports under its own observability, not the default's."""
        db = _db(
            [],
            [("support", 5, {"observability": {"content": "none"}})],
            [("support", "staging", 2, {"observability": {"token_secret_id": str(uuid.uuid4())}})],
        )

        section = await _tracing(db)

        assert section.rows[1][1:] == ["default v5", "-", "content: none"]
        assert section.rows[2][1:] == ["environment staging v2", "own project", "content: full"]

    async def test_without_a_token_nothing_is_exported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LOGFIRE_TOKEN", None)
        db = _db([], [], [])

        section = await _tracing(db)

        assert section.rows[0][2:] == ["-", "unset"]


class TestRetention:
    """Counts only - the section exists to size a schedule, not to read rows."""

    async def test_counts_every_store_twice_and_never_selects_a_row(self) -> None:
        db = _db(counts=[10, 4, 9, 3, 8, 2, 7, 1, 6, 0, 5, 0, 4, 0, 3, 0, 2, 0])

        section = await _retention(db, older_than_days=90)

        assert len(section.rows) == 9
        assert section.rows[0] == ["conversations", 10, 4]
        assert "90 days" in section.title
        db.execute.assert_not_called()

    async def test_counts_the_stores_deleting_a_conversation_never_reaches(self) -> None:
        """An embed visitor and a user-scoped workspace outlive the conversation."""
        db = _db(counts=[0] * 18)

        section = await _retention(db, older_than_days=365)

        assert [row[0] for row in section.rows][-2:] == ["embed_visitors", "agent_workspaces"]

    async def test_an_empty_store_counts_as_zero_rather_than_none(self) -> None:
        db = _db(counts=[None] * 18)

        section = await _retention(db, older_than_days=365)

        assert all(row[1] == 0 and row[2] == 0 for row in section.rows)


class TestUnreferencedMedia:
    """The one number a reviewer cannot re-derive from the database alone."""

    def test_walk_skips_what_has_no_row_by_design(self, tmp_path) -> None:
        (tmp_path / "user").mkdir()
        (tmp_path / "user" / "a.pdf").write_text("x")
        (tmp_path / "generated_org").mkdir()
        (tmp_path / "generated_org" / "chart.png").write_text("x")
        (tmp_path / "_rag_tmp").mkdir()
        (tmp_path / "_rag_tmp" / "scratch.pdf").write_text("x")

        assert _walk_media(tmp_path) == ["user/a.pdf"]

    def test_a_missing_media_dir_is_no_files_rather_than_an_error(self, tmp_path) -> None:
        assert _walk_media(tmp_path / "absent") == []

    async def test_counts_only_the_files_no_row_points_at(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "user").mkdir()
        (tmp_path / "user" / "kept.pdf").write_text("x")
        (tmp_path / "user" / "orphan.pdf").write_text("x")
        monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
        db = _db([("user/kept.pdf",)], *([[]] * (len(MEDIA_PATH_COLUMNS) - 1)))

        section = await _unreferenced_media(db)

        assert section.rows == [["user", 1]]
        assert "(1 under" in section.title

    async def test_names_no_file_because_a_stored_path_carries_its_filename(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The report is written to be attached to a review, so it counts."""
        (tmp_path / "chat" / "0f1e").mkdir(parents=True)
        (tmp_path / "chat" / "0f1e" / "medical-results.pdf").write_text("x")
        (tmp_path / "chat" / "0f1e" / "payslip.pdf").write_text("x")
        monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
        db = _db(*([[]] * len(MEDIA_PATH_COLUMNS)))

        section = await _unreferenced_media(db)

        assert section.rows == [["chat/0f1e", 2]]
        assert "medical-results" not in str(section.rows)
        assert "(2 under" in section.title

    def test_every_media_path_column_the_models_declare_is_in_the_list(self) -> None:
        listed = {(column.parent.class_.__name__, column.key) for column in MEDIA_PATH_COLUMNS}
        declared = {
            (mapper.class_.__name__, column.key)
            for mapper in Base.registry.mappers
            for column in inspect(mapper.class_).column_attrs
            if column.key in MEDIA_COLUMN_NAMES
        }

        assert declared == listed


class TestTheReportItself:
    """What the command prints, and what it refuses to print."""

    def test_settings_never_print_a_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "LOGFIRE_TOKEN", "pylf_v1_eu_secret")
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
        monkeypatch.setattr(settings, "POSTGRES_SSLMODE", "require")
        monkeypatch.setattr(settings, "MEM0_ALLOWED_HOSTS", ["mem0.internal"])

        cells = _cells(_settings_section())

        assert "pylf_v1_eu_secret" not in cells
        assert "client-id.apps.googleusercontent.com" not in cells
        assert cells.count("set") == 2
        assert "require" in cells
        assert "mem0.internal" in cells

    def test_an_unconfigured_deployment_reports_the_quiet_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LOGFIRE_TOKEN", None)
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
        monkeypatch.setattr(settings, "POSTGRES_SSLMODE", "")
        monkeypatch.setattr(settings, "MEM0_ALLOWED_HOSTS", [])

        cells = _cells(_settings_section())

        assert cells.count("unset") == 3
        assert "none" in cells

    def test_the_settings_say_which_mail_path_is_live(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With EMAIL_PROVIDER=log the SMTP rows describe a hop nobody takes."""
        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "log")

        cells = _cells(_settings_section())

        assert "EMAIL_PROVIDER" in cells
        assert "log" in cells

    def test_an_empty_section_says_so_rather_than_printing_a_bare_heading(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render(Section(title="Empty", note="nothing configured", headers=("A",), rows=[]))

        assert "(none)" in capsys.readouterr().out

    def test_a_populated_section_prints_its_rows(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render(Section(title="Full", note="one row", headers=("A",), rows=[["value"]]))

        out = capsys.readouterr().out
        assert "## Full" in out
        assert "value" in out

    async def test_collect_walks_every_section_in_one_session(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
        db = MagicMock()
        db.execute = AsyncMock(return_value=_result([]))
        db.scalar = AsyncMock(return_value=0)

        @asynccontextmanager
        async def _context():
            yield db

        with patch.object(report, "get_db_context", _context):
            sections = await _collect(365)

        assert [section.title for section in sections][:2] == [
            "Deployment settings",
            "Model destinations",
        ]
        assert len(sections) == 10

    def test_a_cell_cannot_carry_bytes_the_terminal_would_act_on(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An MCP server's name is typed by a tenant; an operator reads this in a shell."""
        forged = "server\x1b[2Jcleared"

        _render(Section(title="Full", note="one row", headers=("A",), rows=[[forged]]))

        out = capsys.readouterr().out
        assert "\x1b[2J" not in out
        assert "\\x1bcleared" in out.replace("[2J", "")

    def test_the_command_prints_the_sections_and_the_condition_it_cannot_check(self) -> None:
        sections = [Section(title="Model destinations", note="n", headers=("A",), rows=[["x"]])]

        with patch.object(report, "_collect", AsyncMock(return_value=sections)):
            result = CliRunner().invoke(data_protection_report, ["--older-than", "90"])

        assert result.exit_code == 0
        assert "## Model destinations" in result.output
        assert "processing agreement" in result.output
