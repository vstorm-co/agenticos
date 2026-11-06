"""Vault-only SSH transport for pinned Mirage: no host config, agent or local keys.

Mirage 0.0.8 has no connection-factory hook. This adapter overrides its accessor's
connection setup and retains the inherited SFTP operations and connection cleanup.
The protected connection fields are pinned by transport and lifecycle tests.
"""

import asyncio
from collections.abc import Mapping

import asyncssh
from mirage.accessor.ssh import SSHAccessor
from mirage.concurrency.limiter import settle
from mirage.vfs.ssh import SSHVFS
from mirage.vfs.ssh.config import SSHConfig as LibrarySSHConfig
from pydantic import Field, SecretStr, field_validator

from app.agents.capabilities.mirage._resolved import MountValue


class VaultSSHConfig(LibrarySSHConfig):
    username: str = Field(min_length=1)
    password: SecretStr = Field(...)
    host_key: str = Field(
        max_length=16384,
        description="The server's public SSH host key, e.g. ssh-ed25519 AAAA…; not a private key or file path.",
    )

    @field_validator("host_key")
    @classmethod
    def public_host_key(cls, value: str) -> str:
        line = value.strip()
        if "\n" in line or not line.startswith(("ssh-", "ecdsa-sha2-", "sk-")):
            raise ValueError("Supply the server's public SSH host key")
        try:
            asyncssh.import_public_key(line)
        except asyncssh.KeyImportError as exc:
            raise ValueError("Supply the server's public SSH host key") from exc
        return line


class VaultSSHAccessor(SSHAccessor):
    def __init__(self, config: VaultSSHConfig) -> None:
        super().__init__(config)
        self._vault_config = config
        self._trusted_host_key = asyncssh.import_public_key(config.host_key)

    async def sftp(self) -> asyncssh.SFTPClient:
        async with self._lock:
            if self._conn is not None and self._conn.is_closed():
                self._conn = None
                self._sftp = None
            if self._sftp is None:
                conn = await asyncssh.connect(
                    host=self._vault_config.hostname or self._vault_config.host,
                    port=self._vault_config.port or 22,
                    username=self._vault_config.username,
                    password=self._vault_config.password.get_secret_value(),
                    known_hosts=([self._trusted_host_key], [], []),
                    config=None,
                    client_keys=[],
                    agent_path=None,
                    public_key_auth=False,
                    kbdint_auth=False,
                    gss_auth=False,
                    gss_kex=False,
                    host_based_auth=False,
                    preferred_auth="password",
                    connect_timeout=self._vault_config.timeout,
                    login_timeout=self._vault_config.timeout,
                )
                try:
                    self._sftp = await conn.start_sftp_client()
                except BaseException:
                    conn.close()
                    await settle(asyncio.ensure_future(conn.wait_closed()))
                    raise
                self._conn = conn
            return self._sftp


def build_ssh(config: Mapping[str, MountValue]) -> SSHVFS:
    validated = VaultSSHConfig.model_validate(config)
    vfs = SSHVFS(validated)
    vfs.accessor = VaultSSHAccessor(validated)
    return vfs
