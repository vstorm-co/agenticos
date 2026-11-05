"""The terminal never borrows API-host SSH identities or trusts an unpinned server."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import asyncssh
import pytest
from pydantic import ValidationError

from app.agents.capabilities.mirage._ssh import VaultSSHAccessor, VaultSSHConfig, build_ssh

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _config(**overrides: object) -> VaultSSHConfig:
    key = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
    return VaultSSHConfig.model_validate(
        {
            "host": "127.0.0.1",
            "username": "vault-user",
            "password": "vault-password",
            "host_key": key,
            **overrides,
        }
    )


def test_ssh_requires_a_public_host_key_and_explicit_vault_authentication() -> None:
    for invalid in ("/Users/somebody/.ssh/id_ed25519", "ssh-ed25519 not-a-public-key"):
        with pytest.raises(ValidationError, match="public SSH host key"):
            _config(host_key=invalid)
    private_key = asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()
    with pytest.raises(ValidationError, match="public SSH host key"):
        _config(host_key=private_key)
    for field in ("password", "username", "host_key"):
        data = _config().model_dump()
        del data[field]
        with pytest.raises(ValidationError, match=field):
            VaultSSHConfig.model_validate(data)


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_ssh_closes_a_connection_when_sftp_opening_fails(
    monkeypatch: pytest.MonkeyPatch, error_type: type[BaseException]
) -> None:
    connection = MagicMock(spec=asyncssh.SSHClientConnection)
    connection.start_sftp_client = AsyncMock(side_effect=error_type())
    connection.wait_closed = AsyncMock()
    monkeypatch.setattr(asyncssh, "connect", AsyncMock(return_value=connection))
    config = _config(
        hostname="remote.internal" if error_type is RuntimeError else None,
        port=2022 if error_type is RuntimeError else None,
    )
    accessor = VaultSSHAccessor(config)
    try:
        with pytest.raises(error_type):
            await accessor.sftp()
        assert asyncssh.connect.await_args.kwargs["host"] == (config.hostname or config.host)
        assert asyncssh.connect.await_args.kwargs["port"] == (config.port or 22)
        connection.close.assert_called_once()
        connection.wait_closed.assert_awaited_once()
    finally:
        await accessor.close()


@pytest.mark.parametrize("wrong_host_key", [False, True])
async def test_real_sftp_uses_only_the_vault_password_and_pinned_host_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrong_host_key: bool
) -> None:
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    connections: set[asyncssh.SSHServerConnection] = set()
    attempts: list[tuple[str, str]] = []

    class Server(asyncssh.SSHServer):
        def connection_made(self, connection: asyncssh.SSHServerConnection) -> None:
            connections.add(connection)

        def begin_auth(self, username: str) -> bool:
            return True

        def password_auth_supported(self) -> bool:
            return True

        def validate_password(self, username: str, password: str) -> bool:
            attempts.append((username, password))
            return username == "vault-user" and password == "vault-password"

    def sftp(channel: asyncssh.SSHServerChannel[bytes]) -> asyncssh.SFTPServer:
        return asyncssh.SFTPServer(channel, chroot=str(tmp_path))

    (tmp_path / "report.txt").write_text("A file from the configured SSH server.")
    listener = await asyncssh.create_server(
        Server, "127.0.0.1", 0, server_host_keys=[host_key], sftp_factory=sftp
    )
    pinned = asyncssh.generate_private_key("ssh-ed25519") if wrong_host_key else host_key
    config = _config(port=listener.get_port(), host_key=pinned.export_public_key().decode())
    connected = MagicMock(wraps=asyncssh.connect)
    monkeypatch.setattr(asyncssh, "connect", connected)
    vfs = build_ssh(config.model_dump())
    try:
        if wrong_host_key:
            with pytest.raises(asyncssh.HostKeyNotVerifiable):
                await vfs.accessor.sftp()
            assert attempts == []
        else:
            first = await vfs.accessor.sftp()
            async with first.open("/report.txt", "rb") as remote:
                assert await remote.read() == b"A file from the configured SSH server."
            assert await vfs.accessor.sftp() is first
            connection = vfs.accessor._conn
            assert connection is not None
            connection.close()
            await connection.wait_closed()
            assert await vfs.accessor.sftp() is not first
            assert attempts == [("vault-user", "vault-password")] * 2
        options = connected.call_args.kwargs
        assert options["config"] is None and options["client_keys"] == []
        assert options["agent_path"] is None
        assert options["public_key_auth"] is False and options["kbdint_auth"] is False
        assert options["preferred_auth"] == "password"
    finally:
        await vfs.accessor.close()
        for connection in connections:
            connection.close()
            await connection.wait_closed()
        listener.close()
        await listener.wait_closed()


def test_mount_validation_does_not_echo_a_rejected_host_key() -> None:
    from uuid import uuid4

    from app.agents.capabilities.mirage import MirageMount

    with pytest.raises(ValidationError) as refused:
        MirageMount.model_validate(
            {
                "path": "/server/",
                "backend": "ssh",
                "secrets": {"password": str(uuid4())},
                "options": {
                    "host": "server.internal",
                    "username": "demo",
                    "host_key": "ssh-ed25519 private-input-marker",
                },
            }
        )
    error = refused.value.errors(include_input=False, include_context=False, include_url=False)[0]
    assert "public SSH host key" in error["msg"]
    assert "private-input-marker" not in error["msg"]
