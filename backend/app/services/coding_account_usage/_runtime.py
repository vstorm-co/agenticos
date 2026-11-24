"""Private native execution and renewable-grant cleanup, without a model turn."""

import json
import logging
from pathlib import Path
from typing import cast
from uuid import uuid4

import anyio
from pydantic_ai.providers.openai_codex import OpenAICodexCredentials
from pydantic_ai.workspaces import Workspace

from app.agents.capabilities.coding_agent._harness import codex_auth_file, rotated_sign_in
from app.core.exceptions import ExternalServiceError
from app.schemas.base import BaseSchema
from app.schemas.coding_account import ProviderModelCatalog, ProviderUsageSnapshot, UsageReasonCode
from app.services.personal_codex import PersonalCodexCredentials

logger = logging.getLogger(__name__)

WRITE_AUTH = [
    "python3",
    "-c",
    """
import os
from pathlib import Path
os.umask(0o077)
home = Path(os.environ['CODEX_HOME'])
home.mkdir(mode=0o700)
(home / 'auth.json').write_text(os.environ['AGENTICOS_CODEX_AUTH'], encoding='utf-8')
""",
]
READ_AUTH = [
    "python3",
    "-c",
    """
import os
import shutil
import sys
from pathlib import Path
home = Path(os.environ['CODEX_HOME'])
try:
    with (home / 'auth.json').open(encoding='utf-8') as source:
        sys.stdout.write(source.read(32768))
except FileNotFoundError:
    pass
finally:
    shutil.rmtree(home, ignore_errors=True)
""",
]


class Observation(BaseSchema):
    usage: ProviderUsageSnapshot
    model_catalog: ProviderModelCatalog


class ProbeUnavailable(ExternalServiceError):
    def __init__(self, reason: UsageReasonCode = "telemetry_unavailable") -> None:
        self.reason = reason
        super().__init__(
            message="The coding account usage probe could not be completed", details={}
        )


async def execute(
    workspace: Workspace,
    written: OpenAICodexCredentials,
    env: dict[str, str],
) -> Observation:
    staged = await workspace.run(
        WRITE_AUTH,
        env={**env, "AGENTICOS_CODEX_AUTH": codex_auth_file(written)},
        timeout=10,
    )
    if staged.exit_code != 0:
        raise ProbeUnavailable()
    command = [
        "python3",
        "-c",
        Path(__file__).with_name("_native_probe.py").read_text(encoding="utf-8"),
    ]
    answer = await workspace.run(
        command,
        env={**env, "AGENTICOS_CODEX_EXPECTED_ACCOUNT": written.account_id},
        timeout=65,
    )
    if answer.exit_code != 0 or len(answer.stdout) > 65536:
        raise ProbeUnavailable()
    value = json.loads(answer.stdout)
    if isinstance(value, dict) and "reason_code" in value:
        reason = value["reason_code"]
        if reason in {
            "provider_identity_mismatch",
            "model_catalog_unverified",
            "runtime_version_unsupported",
            "probe_timeout",
        }:
            raise ProbeUnavailable(cast(UsageReasonCode, reason))
        raise ProbeUnavailable()
    return Observation.model_validate(value)


async def read_usage(workspace: Workspace, source: PersonalCodexCredentials) -> Observation:
    """Stage only this grant, preserve a rotated grant with CAS, then delete its home.

    The account lease is held by the caller across all three operations. Only
    normalized JSON leaves the probe; credential readback follows the existing
    native-auth path and is never returned, audited as stdout, or logged.
    """
    written = await source.load()
    # A new directory in a private disposable remote sandbox, mode 0700, never reused.
    home = f"/tmp/t3os-codex-usage-{uuid4().hex}"  # noqa: S108
    env = {"CODEX_HOME": home}
    try:
        try:
            return await execute(workspace, written, env)
        except ProbeUnavailable:
            raise
        except ValueError, OSError, TimeoutError:
            raise ProbeUnavailable() from None
        except Exception as error:
            # Remote transports may include command environments in an error.
            # Retain its class for diagnosis, never the native error or traceback.
            logger.warning(
                "coding_account_usage_transport_failed", extra={"error_type": type(error).__name__}
            )
            raise ProbeUnavailable() from None
    finally:
        with anyio.move_on_after(15, shield=True):
            try:
                saved = await workspace.run(READ_AUTH, env=env, timeout=10)
                rotated = (
                    rotated_sign_in(saved.stdout, written) if len(saved.stdout) <= 32768 else None
                )
                if rotated is not None:
                    await source.swap(written, rotated)
            except Exception as error:
                logger.warning(
                    "coding_account_usage_cleanup_failed",
                    extra={"error_type": type(error).__name__},
                )
