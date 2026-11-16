"""Headless channel registration keeps bot credentials out of terminal output."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import TextIO
from unittest.mock import AsyncMock
from uuid import uuid4

import click
import pytest
from click.testing import CliRunner

from app.commands import channel


@click.command()
@click.option("--token", default=None)
@click.option("--token-file", type=click.File("r", encoding="utf-8"))
def read_token(token: str | None, token_file: TextIO | None) -> None:
    assert channel._read_bot_token(token, token_file) == "synthetic-test-token"
    click.echo("Credential accepted")


def test_hidden_prompt_does_not_echo_token() -> None:
    result = CliRunner().invoke(read_token, input="synthetic-test-token\n")
    assert result.exit_code == 0
    assert "Credential accepted" in result.output
    assert "synthetic-test-token" not in result.output


@pytest.mark.parametrize("source", ["flag", "file", "stdin"])
def test_supported_sources_preserve_the_token(source: str, tmp_path: Path) -> None:
    token_file = tmp_path / "bot-token"
    token_file.write_text("synthetic-test-token\n", encoding="utf-8")
    args = {
        "flag": ["--token", "synthetic-test-token"],
        "file": ["--token-file", str(token_file)],
        "stdin": ["--token-file", "-"],
    }[source]
    result = CliRunner().invoke(read_token, args, input="synthetic-test-token\n")
    assert result.exit_code == 0
    assert "synthetic-test-token" not in result.output


@pytest.mark.security
def test_conflicting_sources_are_refused_without_echoing_credentials(tmp_path: Path) -> None:
    token_file = tmp_path / "bot-token"
    token_file.write_text("other-secret", encoding="utf-8")
    result = CliRunner().invoke(
        read_token, ["--token", "synthetic-test-token", "--token-file", str(token_file)]
    )
    assert result.exit_code != 0
    assert "not both" in result.output
    assert "synthetic-test-token" not in result.output
    assert "other-secret" not in result.output


@pytest.mark.security
@pytest.mark.parametrize("contents", [" \n", "first\nsecond", "with\x00nul", "a" * 4097])
def test_invalid_token_files_are_refused_without_their_contents(
    contents: str, tmp_path: Path
) -> None:
    token_file = tmp_path / "bot-token"
    token_file.write_text(contents, encoding="utf-8")
    result = CliRunner().invoke(read_token, ["--token-file", str(token_file)])
    assert result.exit_code != 0
    assert "Credential accepted" not in result.output
    assert "first" not in result.output
    assert "a" * 100 not in result.output


@pytest.mark.security
def test_invalid_utf8_is_reported_without_echoing_bytes(tmp_path: Path) -> None:
    token_file = tmp_path / "bot-token"
    token_file.write_bytes(b"private-token\xff")
    result = CliRunner().invoke(read_token, ["--token-file", str(token_file)])
    assert result.exit_code != 0
    assert "UTF-8" in result.output
    assert "private-token" not in result.output


@pytest.mark.parametrize("source", ["prompt", "flag", "file", "stdin"])
def test_registration_uses_the_existing_service_without_echoing_the_token(
    source: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = AsyncMock()
    service.create.return_value = SimpleNamespace(id=uuid4())

    @asynccontextmanager
    async def opened(_org: str | None) -> AsyncIterator[AsyncMock]:
        yield service

    monkeypatch.setattr(channel, "_channel_service", opened)
    token_file = tmp_path / "bot-token"
    token_file.write_text("synthetic-test-token\n", encoding="utf-8")
    source_args = {
        "prompt": [],
        "flag": ["--token", "synthetic-test-token"],
        "file": ["--token-file", str(token_file)],
        "stdin": ["--token-file", "-"],
    }[source]
    result = CliRunner().invoke(
        channel.channel_add_bot,
        ["--platform", "telegram", "--name", "Support", "--mode", "jwt_linked", *source_args],
        input="synthetic-test-token\n",
    )
    assert result.exit_code == 0, result.output
    assert "Bot registered successfully" in result.output
    assert "synthetic-test-token" not in result.output
    assert service.create.await_args is not None
    assert service.create.await_args.args[0].token == "synthetic-test-token"


@pytest.mark.security
def test_read_error_does_not_expose_exception_details() -> None:
    class Unreadable(StringIO):
        def read(self, size: int | None = -1) -> str:
            raise OSError("private-token")

    with pytest.raises(click.ClickException, match="Cannot read") as exc:
        channel._read_bot_token(None, Unreadable())
    assert "private-token" not in str(exc.value)
