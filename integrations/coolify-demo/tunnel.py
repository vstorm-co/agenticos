#!/usr/bin/env python3
"""Forward loopback ports to exact Docker containers through a pinned SSH host.

Requires Paramiko and an authenticated Azure CLI. The private JSON configuration
names host, host_key_sha256, vault_name, ssh_secret_name and mappings containing
local_port, container and container_port. ssh_user defaults to root; ssh_port to
22. Keep that configuration outside version control. The Azure secret must hold
an unencrypted OpenSSH or PEM private key; it is never written to disk.

All listeners bind only 127.0.0.1. Container addresses are resolved at startup,
so restart the helper after a deployment replaces a container. Ctrl+C or SIGTERM
closes the listeners, active connections and SSH transport.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import secrets
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from types import FrameType
from typing import cast

import paramiko

LOOPBACK = "127.0.0.1"
MAX_CONNECTIONS = 64
BUFFER_SIZE = 64 * 1024


class TunnelError(Exception):
    """An operational refusal whose message contains no credentials."""


@dataclass(frozen=True)
class Mapping:
    local_port: int
    container: str
    container_port: int


@dataclass(frozen=True)
class Configuration:
    host: str
    host_key_sha256: str
    ssh_user: str
    ssh_port: int
    vault_name: str
    ssh_secret_name: str
    mappings: tuple[Mapping, ...]


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TunnelError("Expected a JSON object.")
    return cast(dict[str, object], value)


def _text(values: dict[str, object], name: str, default: str | None = None) -> str:
    value = values.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise TunnelError(f"Configuration requires a nonempty {name}.")
    return value.strip()


def _port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise TunnelError("Ports must be integers between 1 and 65535.")
    return value


def read_configuration(path: Path) -> Configuration:
    if path.stat().st_size > 32 * 1024:
        raise TunnelError("Configuration exceeds 32 KiB.")
    values = _object(json.loads(path.read_text(encoding="utf-8-sig")))
    host = _text(values, "host")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,253}", host):
        raise TunnelError("Host must be a plain DNS name or IP address.")
    pin = _text(values, "host_key_sha256").rstrip("=")
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", pin):
        raise TunnelError("host_key_sha256 must be an OpenSSH SHA256 fingerprint.")
    username = _text(values, "ssh_user", "root")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", username):
        raise TunnelError("Invalid SSH username.")
    vault = _text(values, "vault_name")
    secret = _text(values, "ssh_secret_name")
    # az may be a Windows .cmd launcher; shell metacharacters never reach it.
    if not re.fullmatch(r"[A-Za-z0-9-]{3,24}", vault):
        raise TunnelError("Invalid Azure Key Vault name.")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,127}", secret):
        raise TunnelError("Invalid Azure secret name.")
    raw_mappings = values.get("mappings")
    if not isinstance(raw_mappings, list) or not 1 <= len(raw_mappings) <= 16:
        raise TunnelError("Supply between one and sixteen port mappings.")
    mappings: list[Mapping] = []
    for raw in raw_mappings:
        item = _object(raw)
        container = _text(item, "container")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", container):
            raise TunnelError("Use an exact Docker container name without a leading slash.")
        mappings.append(Mapping(_port(item.get("local_port")), container, _port(item.get("container_port"))))
    if len({item.local_port for item in mappings}) != len(mappings):
        raise TunnelError("Local ports must be unique.")
    return Configuration(host, pin, username, _port(values.get("ssh_port", 22)), vault, secret, tuple(mappings))


def load_private_key(config: Configuration) -> paramiko.PKey:
    executable = shutil.which("az")
    if executable is None:
        raise TunnelError("Azure CLI is unavailable; install and sign in before starting the helper.")
    result = subprocess.run(
        [
            executable, "keyvault", "secret", "show",
            "--vault-name", config.vault_name,
            "--name", config.ssh_secret_name,
            "--query", "value", "--output", "json", "--only-show-errors",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise TunnelError("Azure secret lookup failed; verify az sign-in and Key Vault access.")
    raw: object = json.loads(result.stdout)
    if not isinstance(raw, str) or not raw.strip():
        raise TunnelError("The Azure secret did not contain a private-key string.")
    for key_class in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return key_class.from_private_key(io.StringIO(raw))
        except paramiko.PasswordRequiredException:
            raise TunnelError("The private key is encrypted; this helper accepts no passphrase.") from None
        except (paramiko.SSHException, ValueError):
            continue
    raise TunnelError("The Azure secret must contain an unencrypted OpenSSH or PEM private key.")


class PinnedHostKey(paramiko.MissingHostKeyPolicy):
    """Reject every server key except the fingerprint supplied by the operator."""

    def __init__(self, expected: str) -> None:
        self.expected = expected

    def missing_host_key(self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey) -> None:
        digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")
        if not secrets.compare_digest(f"SHA256:{digest}", self.expected):
            raise TunnelError("SSH server key does not match the configured SHA256 pin.")
        # Do not add the key to a shared known_hosts file: the explicit pin is the trust source.


def resolve_container(client: paramiko.SSHClient, name: str) -> str:
    # Deliberately select only identity, state and addresses; a full inspect includes secrets.
    template = '{"name":{{json .Name}},"running":{{json .State.Running}},"networks":{{json .NetworkSettings.Networks}}}'
    command = f"docker inspect --type container --format {shlex.quote(template)} -- {shlex.quote(name)}"
    stdin, stdout, stderr = client.exec_command(command, timeout=15)
    stdin.close()
    try:
        raw = stdout.read(128 * 1024 + 1)
        stderr.read(4096)
        if len(raw) > 128 * 1024 or stdout.channel.recv_exit_status() != 0:
            raise TunnelError("Docker could not inspect the configured container.")
        result = _object(json.loads(raw))
    finally:
        stdout.channel.close()
    if result.get("name") != f"/{name}" or result.get("running") is not True:
        raise TunnelError("The exact configured container is absent or not running.")
    networks = _object(result.get("networks"))
    for network in sorted(networks, key=lambda item: (item != "coolify", item)):
        address = _object(networks[network]).get("IPAddress")
        if isinstance(address, str) and address:
            parsed = ipaddress.ip_address(address)
            if parsed.version == 4 and not parsed.is_unspecified and not parsed.is_loopback:
                return str(parsed)
    raise TunnelError("The configured container has no usable IPv4 address.")


def close_socket(connection: socket.socket) -> None:
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # A peer or an earlier shutdown may already have closed either half.
    connection.close()


def relay(
    connection: socket.socket,
    destination: tuple[str, int],
    transport: paramiko.Transport,
    stop: threading.Event,
    active: dict[socket.socket, paramiko.Channel | None],
    lock: threading.Lock,
) -> None:
    channel: paramiko.Channel | None = None
    try:
        connection.settimeout(15)
        channel = transport.open_channel("direct-tcpip", destination, connection.getpeername(), timeout=15)
        if channel is None:
            raise TunnelError("SSH refused a forwarding channel.")
        channel.settimeout(15)
        with lock:
            active[connection] = channel
        readers: list[socket.socket | paramiko.Channel] = [connection, channel]
        while readers and not stop.is_set():
            ready, _, _ = select.select(readers, [], [], 0.5)
            for source in ready:
                chunk = source.recv(BUFFER_SIZE)
                if chunk:
                    if source is connection:
                        channel.sendall(chunk)
                    else:
                        connection.sendall(chunk)
                else:
                    readers.remove(source)
                    if source is connection:
                        channel.shutdown_write()
                    else:
                        connection.shutdown(socket.SHUT_WR)
    except (ConnectionResetError, BrokenPipeError):
        pass  # Browsers routinely cancel an in-flight request.
    except (OSError, EOFError, ValueError, paramiko.SSHException, TunnelError) as exc:
        if not stop.is_set():
            print(f"Forwarding connection ended ({type(exc).__name__}).", file=sys.stderr, flush=True)
    finally:
        if channel is not None:
            channel.close()
        close_socket(connection)
        with lock:
            active.pop(connection, None)


def run(config: Configuration) -> None:
    stop = threading.Event()
    active: dict[socket.socket, paramiko.Channel | None] = {}
    lock = threading.Lock()
    listeners: dict[socket.socket, tuple[str, int]] = {}
    threads: list[threading.Thread] = []
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedHostKey(config.host_key_sha256))

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    previous_int = signal.signal(signal.SIGINT, request_stop)
    previous_term = signal.signal(signal.SIGTERM, request_stop)
    try:
        private_key = load_private_key(config)
        if stop.is_set():
            return
        client.connect(
            hostname=config.host,
            port=config.ssh_port,
            username=config.ssh_user,
            pkey=private_key,
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            banner_timeout=15,
            auth_timeout=20,
            channel_timeout=15,
        )
        del private_key
        transport = client.get_transport()
        if transport is None or not transport.is_authenticated():
            raise TunnelError("SSH authentication did not establish a transport.")
        transport.set_keepalive(20)
        for mapping in config.mappings:
            destination = (resolve_container(client, mapping.container), mapping.container_port)
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if os.name == "nt":
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((LOOPBACK, mapping.local_port))
                listener.listen(32)
                listener.settimeout(1)
            except BaseException:
                listener.close()
                raise
            listeners[listener] = destination
        if stop.is_set():
            return
        for listener in listeners:
            print(f"Private SSH tunnel listening on {LOOPBACK}:{listener.getsockname()[1]}", flush=True)
        while not stop.is_set():
            if not transport.is_active():
                raise TunnelError("SSH transport closed; local listeners are shutting down.")
            ready, _, _ = select.select(list(listeners), [], [], 0.5)
            for listener in ready:
                connection, _ = listener.accept()
                with lock:
                    if len(active) >= MAX_CONNECTIONS:
                        connection.close()
                        continue
                    active[connection] = None
                worker = threading.Thread(
                    target=relay,
                    args=(connection, listeners[listener], transport, stop, active, lock),
                    daemon=True,
                )
                threads = [thread for thread in threads if thread.is_alive()]
                threads.append(worker)
                worker.start()
    finally:
        stop.set()
        for listener in listeners:
            listener.close()
        with lock:
            connections = list(active.items())
        for connection, channel in connections:
            close_socket(connection)
            if channel is not None:
                channel.close()
        client.close()
        deadline = time.monotonic() + 5
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Private JSON configuration path")
    args = parser.parse_args()
    # Operational failures below are sanitized; never enable SSH packet/debug logging here.
    logging.getLogger("paramiko").addHandler(logging.NullHandler())
    logging.getLogger("paramiko").propagate = False
    try:
        run(read_configuration(args.config))
    except TunnelError as exc:
        print(f"Private tunnel refused: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, paramiko.SSHException, subprocess.SubprocessError) as exc:
        print(f"Private tunnel failed ({type(exc).__name__}); no credentials were logged.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
