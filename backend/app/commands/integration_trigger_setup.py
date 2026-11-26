"""Prepare polled integration routines offline; explicitly create them paused by API."""

from typing import Literal, TextIO
from uuid import UUID

import click
import httpx
from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from app.commands import command
from app.core.exceptions import AppException
from app.schemas.agent_trigger import TriggerCreate
from app.schemas.portal import PortalCatalog
from app.services import portal_catalog
from app.services.portals.github_app_manifest import https_origin

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class CreatedRoutine(BaseModel):
    id: UUID
    agent_id: UUID
    connection_id: UUID
    is_active: Literal[False]
    delivery_mode: Literal["polling"]


def _read_text(source: TextIO, limit: int, label: str) -> str:
    try:
        value = source.read(limit + 1)
    except OSError, UnicodeError:
        raise click.ClickException(f"Cannot read {label}.") from None
    if not value.strip() or len(value) > limit:
        raise click.UsageError(f"{label} must contain between 1 and {limit} characters.")
    return value


def _authentication(
    base_url: str | None, org: UUID | None, source: TextIO | None
) -> tuple[str, str]:
    if base_url is None or org is None:
        raise click.UsageError("--apply and --accounts require --base-url and --org.")
    try:
        origin = https_origin(base_url)
    except AppException as exc:
        raise click.UsageError(exc.message) from None
    token = (
        _read_text(source, 8192, "access-token file").strip()
        if source
        else click.prompt("AgenticOS access token", hide_input=True).strip()
    )
    if (
        not token
        or len(token) > 8192
        or not token.isascii()
        or any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in token)
    ):
        raise click.UsageError("Use a valid access token without whitespace or control characters.")
    return origin, token


def _accounts(*, origin: str, org: UUID, token: str, portal: str | None) -> None:
    try:
        with (
            httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client,
            client.stream(
                "GET",
                f"{origin}/api/v1/trigger-portals",
                headers={"Authorization": f"Bearer {token}", "X-Organization-Id": str(org)},
            ) as response,
        ):
            if response.status_code != 200:
                raise click.ClickException(
                    f"Account listing refused (HTTP {response.status_code})."
                )
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                body.extend(chunk)
                if len(body) > 1048576:
                    raise click.ClickException("Account listing exceeds the setup limit.")
            catalog = PortalCatalog.model_validate_json(body)
    except httpx.HTTPError, ValidationError:
        raise click.ClickException("Cannot read the account catalog from this instance.") from None
    for entry in catalog.items:
        if (
            entry.delivery == "polling"
            and entry.native_provider
            and (portal is None or portal == entry.key)
        ):
            click.echo(f"Portal: {entry.key}")
            click.echo(entry.model_dump_json(include={"connection_state", "connect_blocked_by"}))
            for account in entry.connection_choices:
                click.echo(
                    account.model_dump_json(
                        include={
                            "id",
                            "provider",
                            "email",
                            "name",
                            "label",
                            "owner",
                            "needs_reconnect",
                            "polling_failed",
                        }
                    )
                )
            if not entry.connection_choices:
                click.echo(
                    "No eligible account for this portal. Check connection, scopes and account access before applying."
                )


def _submit(
    *, origin: str, org: UUID, agent: UUID, connection: UUID, token: str, data: TriggerCreate
) -> UUID:
    # API authorization and source validation remain authoritative. Never retry a
    # POST whose response was lost: it may already have created a paused routine.
    try:
        with (
            httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client,
            client.stream(
                "POST",
                f"{origin}/api/v1/agents/{agent}/triggers",
                headers={"Authorization": f"Bearer {token}", "X-Organization-Id": str(org)},
                json=data.model_dump(mode="json", exclude_none=True),
            ) as response,
        ):
            if response.status_code != 201:
                raise click.ClickException(
                    f"Routine creation was not confirmed (HTTP {response.status_code}). "
                    "Check agent access, selected account and preset fields. "
                    "Inspect existing routines before retrying."
                )
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                body.extend(chunk)
                if len(body) > 65536:
                    raise click.ClickException("Routine response exceeds the setup limit.")
            created = CreatedRoutine.model_validate_json(body)
            if created.agent_id != agent or created.connection_id != connection:
                raise click.ClickException("Routine response does not match the selected source.")
            return created.id
    except httpx.HTTPError, ValidationError:
        raise click.ClickException(
            "Routine creation was not confirmed. Inspect existing routines before retrying."
        ) from None


@command(
    "integration-trigger-setup", help="List or prepare polled routines; --apply creates paused"
)
@click.option("--list", "list_presets", is_flag=True, help="List polling portals/presets offline.")
@click.option(
    "--accounts", is_flag=True, help="Read accessible accounts/status from your instance API."
)
@click.option("--portal", help="Portal key from --list, such as google or outlook_calendar.")
@click.option("--preset", help="Preset key from --list, such as inbox_only.")
@click.option("--agent", type=click.UUID, help="Agent UUID in the destination organization.")
@click.option("--connection", type=click.UUID, help="Exact connected-account UUID; never inferred.")
@click.option("--name", help="Optional routine title, at most 120 characters.")
@click.option("--prompt-file", type=click.File("r", encoding="utf-8"), help="Routine instructions.")
@click.option(
    "--filter-file",
    type=click.File("r", encoding="utf-8"),
    help="JSON object of preset filter overrides; checked by the server on --apply.",
)
@click.option(
    "--apply", is_flag=True, help="Create a paused routine through the authenticated API."
)
@click.option(
    "--base-url", help="Your AgenticOS HTTPS origin; required with --accounts or --apply."
)
@click.option(
    "--org",
    type=click.UUID,
    help="Destination organization UUID; required with --accounts or --apply.",
)
@click.option(
    "--access-token-file",
    type=click.File("r", encoding="utf-8"),
    help="Protected AgenticOS access-token file; otherwise hidden input for API access.",
)
def integration_trigger_setup(
    list_presets: bool,
    accounts: bool,
    portal: str | None,
    preset: str | None,
    agent: UUID | None,
    connection: UUID | None,
    name: str | None,
    prompt_file: TextIO | None,
    filter_file: TextIO | None,
    apply: bool,
    base_url: str | None,
    org: UUID | None,
    access_token_file: TextIO | None,
) -> None:
    if sum((list_presets, accounts, apply)) > 1:
        raise click.UsageError("Choose --list, --accounts or --apply, not several modes.")
    if accounts:
        if org is None:
            raise click.UsageError("--accounts requires --org.")
        if portal is not None:
            entry = portal_catalog.get_portal(portal)
            if (
                entry is None
                or entry.delivery != portal_catalog.DeliveryMode.POLLING
                or not entry.native_provider
            ):
                raise click.UsageError("Choose a native polling portal from --list.")
        origin, token = _authentication(base_url, org, access_token_file)
        _accounts(origin=origin, org=org, token=token, portal=portal)
        return
    if list_presets:
        for entry in portal_catalog.CATALOG:
            if entry.delivery == portal_catalog.DeliveryMode.POLLING and entry.native_provider:
                for item in entry.presets:
                    click.echo(f"{entry.key}\t{item.key}\t{item.label}")
        return
    selected = portal_catalog.get_preset(portal or "", preset or "")
    if selected is None:
        raise click.UsageError("Choose a portal and preset from --list.")
    entry, item = selected
    if entry.delivery != portal_catalog.DeliveryMode.POLLING or not entry.native_provider:
        raise click.UsageError("This command accepts native polling portals only.")
    if item.target_required:
        raise click.UsageError("This preset requires target selection in Routines.")
    if agent is None or connection is None or prompt_file is None:
        raise click.UsageError("Provide --agent, --connection and --prompt-file.")
    try:
        overrides = (
            _JSON_OBJECT.validate_json(_read_text(filter_file, 16384, "filter file"))
            if filter_file
            else None
        )
        data = TriggerCreate(
            name=name,
            prompt=_read_text(prompt_file, 10000, "prompt file"),
            trigger_type="event",
            portal_key=entry.key,
            preset_key=item.key,
            connection_id=connection,
            event_config=overrides,
            is_active=False,
            review_before_activation=True,
        )
    except ValidationError:
        raise click.UsageError(
            "Invalid prompt, name or filter JSON; no request was sent."
        ) from None
    if not apply:
        if access_token_file is not None:
            raise click.UsageError("An access token is only used with --apply.")
        click.echo(data.model_dump_json(exclude_none=True, indent=2))
        click.echo("Offline only: account access and filter semantics are not checked.", err=True)
        return
    if org is None:
        raise click.UsageError("--apply requires --base-url and --org.")
    origin, token = _authentication(base_url, org, access_token_file)
    routine = _submit(
        origin=origin, org=org, agent=agent, connection=connection, token=token, data=data
    )
    click.echo(f"Created paused routine: {routine}")
    click.echo("Review and approve its sources in Routines before activation. No agent was run.")
