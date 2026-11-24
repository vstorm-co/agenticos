"""Codex 0.160.0 read-only probe, also executed verbatim in a Python 3.12 workbench.

Only stdlib imports belong here. No thread or turn is created. Provider payloads,
errors, account identifiers and native stderr never leave this process.
"""

import asyncio
import contextlib
import hmac
import json
import os
import re
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict, cast

VERSION = "0.160.0"
MAX_BYTES = 2 * 1024 * 1024
MAX_MODELS = 200
TTL_SECONDS = 300
MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._:/-]{0,127}$")


class Window(TypedDict):
    name: str
    used: int
    limit: int
    unit: str
    resets_at: str | None
    window_duration_minutes: int | None


class Usage(TypedDict):
    status: str
    source: str
    observed_at: str
    valid_until: str
    windows: list[Window]
    reason_code: str | None


class Models(TypedDict):
    status: str
    source: str
    observed_at: str | None
    valid_until: str | None
    model_ids: list[str]
    reason_code: str | None


class Observation(TypedDict):
    usage: Usage
    model_catalog: Models


class ProbeFailure(ValueError):
    """Only a fixed, allowlisted reason may cross the process boundary."""


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ProbeFailure("telemetry_unavailable")
    return cast(dict[str, object], value)


def usage_snapshot(response: dict[str, object], expected: str, now: datetime) -> Usage:
    account = response.get("accountId")
    if (
        not expected
        or not isinstance(account, str)
        or not hmac.compare_digest(account.encode(), expected.encode())
    ):
        raise ProbeFailure("provider_identity_mismatch")
    snapshot = mapping(response.get("rateLimits"))
    windows: list[Window] = []
    for name in ("primary", "secondary"):
        value = snapshot.get(name)
        if value is None:
            continue
        window = mapping(value)
        used = window.get("usedPercent")
        if type(used) is not int or used < 0:
            raise ProbeFailure("telemetry_unavailable")
        duration = window.get("windowDurationMins")
        reset = window.get("resetsAt")
        if duration is not None and (type(duration) is not int or duration <= 0):
            raise ProbeFailure("telemetry_unavailable")
        if reset is not None and (type(reset) is not int or not 0 <= reset <= 253402300799):
            raise ProbeFailure("telemetry_unavailable")
        windows.append(
            Window(
                name=name,
                used=used,
                limit=100,
                unit="percent",
                resets_at=datetime.fromtimestamp(reset, UTC).isoformat()
                if reset is not None
                else None,
                window_duration_minutes=duration,
            )
        )
    allowed = response.get("ordinaryUsageAllowed")
    status: str = "unknown"
    reason: str | None = "provider_readiness_unavailable"
    if allowed is True and windows:
        status, reason = "available", None
    elif allowed is False:
        status, reason = "capacity_unavailable", "provider_capacity_unavailable"
        reached = snapshot.get("rateLimitReachedType")
        if reached == "rate_limit_reached":
            status, reason = "rate_limited", "provider_reported_rate_limit"
        elif reached in (
            "workspace_owner_credits_depleted",
            "workspace_member_credits_depleted",
            "workspace_owner_usage_limit_reached",
            "workspace_member_usage_limit_reached",
        ):
            status, reason = "quota_exhausted", "provider_reported_quota_exhausted"
    return Usage(
        status=status,
        source="native_runtime",
        observed_at=now.isoformat(),
        valid_until=(now + timedelta(seconds=TTL_SECONDS)).isoformat(),
        windows=windows,
        reason_code=reason,
    )


def advertised_models(cache: object, listed: set[str], started: datetime, now: datetime) -> Models:
    """A fresh private home proves remote advertisement, never per-call entitlement.

    At the pinned release model/list can silently use bundled metadata after a
    failed remote fetch. Only a newly written, scoped, version-matched native
    cache is evidence of a remote catalog. Its identity stays inside the sandbox.
    """
    unknown = Models(
        status="unknown",
        source="unavailable",
        observed_at=None,
        valid_until=None,
        model_ids=[],
        reason_code="model_catalog_unverified",
    )
    if not isinstance(cache, dict):
        return unknown
    if (
        cache.get("client_version") != VERSION
        or not isinstance(cache.get("identity"), str)
        or not cache["identity"]
    ):
        return unknown
    fetched = cache.get("fetched_at")
    if not isinstance(fetched, str):
        return unknown
    try:
        observed = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
    except ValueError:
        return unknown
    if observed.tzinfo is None or observed < started or observed > now + timedelta(seconds=60):
        return unknown
    records = cache.get("models")
    if not isinstance(records, list) or len(records) > MAX_MODELS:
        return unknown
    remote = {
        item["slug"]
        for item in records
        if isinstance(item, dict)
        and isinstance(item.get("slug"), str)
        and MODEL_ID.fullmatch(item["slug"])
    }
    matched = sorted(remote.intersection(listed))
    if not matched:
        return unknown
    return Models(
        status="advertised",
        source="native_runtime",
        observed_at=observed.isoformat(),
        valid_until=(observed + timedelta(seconds=TTL_SECONDS)).isoformat(),
        model_ids=matched,
        reason_code=None,
    )


async def stop(process: asyncio.subprocess.Process) -> None:
    """Bound shutdown even when a native process stops reading stdin."""
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 2)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        await asyncio.wait_for(process.wait(), 2)


def child_environment(home: Path) -> dict[str, str]:
    """Do not let an ambient API key or provider override replace the selected grant."""
    result = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OPENAI_", "CODEX_", "AGENTICOS_CODEX_"))
    }
    result["CODEX_HOME"] = str(home)
    return result


async def start(*arguments: str, home: Path) -> asyncio.subprocess.Process:
    return await asyncio.wait_for(
        asyncio.create_subprocess_exec(
            "codex",
            *arguments,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=child_environment(home),
            cwd=str(home),
            start_new_session=os.name == "posix",
            limit=MAX_BYTES,
        ),
        5,
    )


class Rpc:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self.next_id = 0
        self.received = 0

    async def send(self, message: dict[str, object]) -> None:
        if self.process.stdin is None:
            raise ProbeFailure("telemetry_unavailable")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        await asyncio.wait_for(self.process.stdin.drain(), 2)

    async def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.next_id += 1
        await self.send({"id": self.next_id, "method": method, "params": params})
        if self.process.stdout is None:
            raise ProbeFailure("telemetry_unavailable")
        async with asyncio.timeout(10):
            for _ in range(32):
                line = await self.process.stdout.readline()
                self.received += len(line)
                if not line or self.received > MAX_BYTES:
                    raise ProbeFailure("telemetry_unavailable")
                message = mapping(json.loads(line))
                # Native notifications are ignored. No approval or model request is answered.
                if type(message.get("id")) is not int or message.get("id") != self.next_id:
                    continue
                if "error" in message:
                    raise ProbeFailure("telemetry_unavailable")
                return mapping(message.get("result"))
        raise ProbeFailure("telemetry_unavailable")


def verify_auth_identity(home: Path, expected: str) -> None:
    """Bind the final catalog to the selected grant after any native token rotation."""
    try:
        with (home / "auth.json").open(encoding="utf-8") as source:
            raw = source.read(32769)
        if len(raw) > 32768:
            account: object = None
        else:
            account = mapping(mapping(json.loads(raw)).get("tokens")).get("account_id")
    except (OSError, ValueError):
        account = None
    if (
        not expected
        or not isinstance(account, str)
        or not hmac.compare_digest(account.encode(), expected.encode())
    ):
        raise ProbeFailure("provider_identity_mismatch")


async def read_models(rpc: Rpc, cache_path: Path, started: datetime) -> Models:
    listed: set[str] = set()
    cursor: str | None = None
    cursors: set[str] = set()
    for _ in range(4):
        page = await rpc.call("model/list", {"includeHidden": False, "limit": 50, "cursor": cursor})
        rows = page.get("data")
        if not isinstance(rows, list) or len(rows) > 50:
            raise ProbeFailure("model_catalog_unverified")
        for row in rows:
            model = mapping(row).get("model")
            if isinstance(model, str) and MODEL_ID.fullmatch(model):
                listed.add(model)
        cursor = cast(str | None, page.get("nextCursor"))
        if cursor is None:
            break
        if not isinstance(cursor, str) or len(cursor) > 256 or cursor in cursors:
            raise ProbeFailure("model_catalog_unverified")
        cursors.add(cursor)
    else:
        raise ProbeFailure("model_catalog_unverified")
    cache: object = None
    with contextlib.suppress(OSError, ValueError):
        with cache_path.open("rb") as source:
            encoded = source.read(MAX_BYTES + 1)
        if len(encoded) <= MAX_BYTES:
            cache = json.loads(encoded)
    return advertised_models(cache, listed, started, datetime.now(UTC))


async def collect(home: Path, expected: str) -> Observation:
    cache_path = home / "models_cache.json"
    if cache_path.exists():
        raise ProbeFailure("model_catalog_unverified")
    version = await start("--version", home=home)
    try:
        if version.stdout is None:
            raise ProbeFailure("runtime_version_unsupported")
        reported = await asyncio.wait_for(version.stdout.read(256), 5)
        await asyncio.wait_for(version.wait(), 2)
        if version.returncode != 0 or reported.strip() != f"codex-cli {VERSION}".encode():
            raise ProbeFailure("runtime_version_unsupported")
    finally:
        await stop(version)
    started = datetime.now(UTC)
    process = await start("app-server", "--listen", "stdio://", home=home)
    try:
        rpc = Rpc(process)
        await rpc.call("initialize", {"clientInfo": {"name": "t3os_account_usage", "version": "1"}})
        await rpc.send({"method": "initialized", "params": {}})
        quota = await rpc.call(
            "account/rateLimits/read",
            {"excludeResetCreditDetails": True, "supportsLunaReserve": False},
        )
        usage = usage_snapshot(quota, expected, datetime.now(UTC))
        try:
            # Model discovery has its own budget so its outage cannot discard
            # an already verified quota observation or exhaust process cleanup.
            async with asyncio.timeout(8):
                models = await read_models(rpc, cache_path, started)
        except (ValueError, OSError, TimeoutError):
            models = advertised_models(None, set(), started, datetime.now(UTC))
        verify_auth_identity(home, expected)
        return Observation(usage=usage, model_catalog=models)
    finally:
        await stop(process)


async def main() -> None:
    try:
        async with asyncio.timeout(55):
            result: Observation | dict[str, str] = await collect(
                Path(os.environ["CODEX_HOME"]), os.environ["AGENTICOS_CODEX_EXPECTED_ACCOUNT"]
            )
    except ProbeFailure as failure:
        result = {"reason_code": str(failure)}
    except TimeoutError:
        result = {"reason_code": "probe_timeout"}
    except (OSError, ValueError, KeyError):
        result = {"reason_code": "telemetry_unavailable"}
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
