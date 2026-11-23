"""Sanitize runtime-owned credential status without reading its secrets or account ID."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from app.agents.capabilities.coding_agent._acp import AcpError, Conversation
from app.agents.capabilities.coding_agent._harness import RuntimeCredentials


class _VibeStatus(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    authenticated: StrictBool
    authState: Literal[
        "os_keyring",
        "vibe_home_env_file",
        "process_env",
        "signed_out",
        "auth_not_required",
        "unsupported_provider",
    ]
    signOutAvailable: StrictBool


class _MuseStatus(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    state: Literal["envKey", "apiKey", "accountLogin", "loggedOut"]
    credentialRequired: StrictBool


async def probe_credentials(
    conversation: Conversation, auth_method: str | None
) -> RuntimeCredentials | None:
    if auth_method in {"muse-cli", "muse-api-key"}:
        raw = await conversation.request("_auth/status", {})
        try:
            muse = _MuseStatus.model_validate(raw)
        except ValidationError as invalid:
            raise AcpError(
                "Muse returned unsupported credential status. No prompt was submitted."
            ) from invalid
        if not muse.credentialRequired or muse.state == "loggedOut":
            raise AcpError(
                "Muse needs a verified Meta account or API key. Complete its own setup; keyless or alternate-provider routing is not admitted by this template."
            )
        if auth_method == "muse-api-key" and muse.state != "envKey":
            raise AcpError(
                "Muse did not confirm the required environment API key. No saved account or key was selected."
            )
        return RuntimeCredentials(
            kind="oauth" if muse.state == "accountLogin" else "api_key",
            source="environment" if muse.state == "envKey" else "cli_file",
            sign_out_available=False,
        )
    if auth_method != "browser-auth":
        return None
    raw = await conversation.request("_auth/status", {})
    try:
        status = _VibeStatus.model_validate(raw)
    except ValidationError as exc:
        raise AcpError(
            "Mistral Vibe returned unsupported credential status; no prompt was submitted."
        ) from exc
    if not status.authenticated or status.authState not in {
        "os_keyring",
        "vibe_home_env_file",
        "process_env",
    }:
        raise AcpError(
            "Mistral Vibe has no supported Mistral credential. Complete its own setup; no alternate provider was selected."
        )
    source: Literal["os_keyring", "cli_file", "environment"]
    match status.authState:
        case "os_keyring":
            source = "os_keyring"
        case "vibe_home_env_file":
            source = "cli_file"
        case _:
            source = "environment"
    return RuntimeCredentials(
        kind="api_key", source=source, sign_out_available=status.signOutAvailable
    )
