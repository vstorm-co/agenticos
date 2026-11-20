"""OS identities for the native Claude account owned by one T3OS member."""

import ctypes
import hashlib
import os
import resource
import signal
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

MAX_HOME_BYTES = 512 * 1024 * 1024
MAX_HOME_ENTRIES = 20000


class RuntimeFailure(Exception):
    """Only fixed public codes cross the runtime boundary, never CLI output."""

    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Owner:
    organization_id: UUID
    user_id: UUID

    @property
    def key(self) -> str:
        return hashlib.sha256(
            f"{self.organization_id}:{self.user_id}".encode()
        ).hexdigest()


@dataclass(frozen=True)
class Home:
    path: Path
    uid: int


class Homes:
    """Permanent, non-recycled UIDs and private homes; the CLI owns its credentials."""

    def __init__(self, root: Path) -> None:
        if os.geteuid() != 0:
            raise RuntimeError(
                "Native account isolation requires the container supervisor"
            )
        self.root = root
        self.users = root / "users"
        self.metadata = root / "metadata"
        for path, mode in ((root, 0o711), (self.users, 0o711), (self.metadata, 0o700)):
            path.mkdir(mode=mode, parents=True, exist_ok=True)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
                raise RuntimeError("Invalid native state directory")
            path.chmod(mode)
        database = self.metadata / "owners.sqlite3"
        if database.is_symlink() or (database.exists() and database.stat().st_uid != 0):
            raise RuntimeError("Invalid native account registry")
        self.db = sqlite3.connect(database)
        database.chmod(0o600)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS owners (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_key TEXT UNIQUE NOT NULL)"
        )
        self.db.commit()

    def get(self, owner: Owner, *, create: bool = False) -> Home | None:
        row = self.db.execute(
            "SELECT id FROM owners WHERE owner_key = ?", (owner.key,)
        ).fetchone()
        if row is None:
            if not create:
                return None
            cursor = self.db.execute(
                "INSERT INTO owners(owner_key) VALUES (?)", (owner.key,)
            )
            self.db.commit()
            row = (cursor.lastrowid,)
        entry_id = row[0]
        if not isinstance(entry_id, int) or isinstance(entry_id, bool) or entry_id < 1:
            raise RuntimeError("Invalid native account registry")
        uid = 20000 + entry_id
        if uid >= 2147483647:
            raise RuntimeFailure("CLAUDE_CAPACITY", 429)
        path = self.users / owner.key
        if not path.exists() and not path.is_symlink():
            if not create:
                return None
            path.mkdir(mode=0o700)
            os.chown(path, uid, uid)
        info = path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != uid
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise RuntimeFailure("CLAUDE_ACCESS_DENIED", 403)
        return Home(path, uid)

    def close(self) -> None:
        self.db.close()


def native_environment(home: Home) -> dict[str, str]:
    """Never inherit application keys, API credentials, provider overrides, or SDK entrypoint overrides."""
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home.path),
        "CLAUDE_CONFIG_DIR": str(home.path / ".claude"),
        "USER": f"claude{home.uid}",
        "LOGNAME": f"claude{home.uid}",
        "LANG": "C.UTF-8",
        "TERM": "xterm-256color",
        "BROWSER": "/bin/false",
        "DISABLE_AUTOUPDATER": "1",
    }


def process_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
    resource.setrlimit(resource.RLIMIT_NPROC, (96, 96))
    resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024 * 1024, 128 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (900, 900))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot enforce native process privileges")


def within_home_limit(home: Home) -> bool:
    """Scan allocated blocks without following symlinks. An incomplete scan refuses use."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    pending: list[int] = []
    entries = 0
    size = 0
    try:
        pending.append(os.open(home.path, flags))
        while pending:
            descriptor = pending.pop()
            try:
                with os.scandir(descriptor) as scan:
                    for entry in scan:
                        entries += 1
                        if entries > MAX_HOME_ENTRIES:
                            return False
                        try:
                            info = os.stat(
                                entry.name, dir_fd=descriptor, follow_symlinks=False
                            )
                        except FileNotFoundError:
                            continue
                        size += info.st_blocks * 512
                        if size > MAX_HOME_BYTES:
                            return False
                        if stat.S_ISDIR(info.st_mode):
                            if len(pending) >= 256:
                                return False
                            try:
                                pending.append(
                                    os.open(entry.name, flags, dir_fd=descriptor)
                                )
                            except (FileNotFoundError, NotADirectoryError):
                                continue
            finally:
                os.close(descriptor)
        return True
    except OSError:
        return False
    finally:
        for descriptor in pending:
            os.close(descriptor)


def signal_native_user(uid: int, sig: signal.Signals) -> None:
    """Stop detached descendants as well as the process group, without a PID reuse race."""
    if not 20000 < uid < 2147483647:
        raise RuntimeError("Invalid native process identity")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        descriptor = None
        try:
            descriptor = os.pidfd_open(int(entry.name))
            status_text = (entry / "status").read_text(encoding="ascii")
            uid_line = next(
                line for line in status_text.splitlines() if line.startswith("Uid:")
            )
            state_line = next(
                line for line in status_text.splitlines() if line.startswith("State:")
            )
            if int(uid_line.split()[1]) == uid and state_line.split()[1] not in {
                "Z",
                "X",
            }:
                signal.pidfd_send_signal(descriptor, sig)
        except (ProcessLookupError, FileNotFoundError):
            continue
        finally:
            if descriptor is not None:
                os.close(descriptor)
