"""Terminal manifest registration with a short-lived loopback callback."""

import http.client
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TextIO
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import click
import httpx
from pydantic import SecretStr, ValidationError

from app.commands import command
from app.core.exceptions import AppException, ExternalServiceError
from app.services.portals.github_app_manifest import (
    EVENT_PERMISSIONS,
    Registration,
    https_origin,
    manifest_for,
    preflight_registration,
    registration_form,
    store_registration,
)


def _convert(code: str) -> Registration:
    # GitHub puts this one-time credential in the URL path. http.client does not
    # produce the automatic URL logs an httpx client would produce here.
    connection = http.client.HTTPSConnection("api.github.com", timeout=30)
    try:
        connection.request(
            "POST",
            f"/app-manifests/{code}/conversions",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "AgenticOS-setup"},
        )
        response = connection.getresponse()
        body = response.read(65537)
        if response.status != 201 or len(body) > 65536:
            raise ExternalServiceError(message="GitHub did not confirm manifest conversion")
        return Registration.model_validate_json(body)
    except OSError, http.client.HTTPException, ValidationError:
        raise ExternalServiceError(message="GitHub manifest conversion was not confirmed") from None
    finally:
        connection.close()


def _wait_for_code(server: HTTPServer, received: list[str], *, timeout: int) -> str:
    deadline = time.monotonic() + timeout
    server.timeout = 1
    while not received and time.monotonic() < deadline:
        server.handle_request()
    if not received:
        raise click.ClickException("Registration timed out. Start a new setup flow.")
    return received[0]


def _handler(state: str, received: list[str]) -> type[BaseHTTPRequestHandler]:
    class Callback(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(5)

        # Preserve the stdlib keyword parameter while disabling credential-bearing URL logs.
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            code = query.get("code", [])
            valid = (
                parsed.path == "/callback"
                and len(query.get("state", [])) == 1
                and secrets.compare_digest(query["state"][0].encode(), state.encode())
                and len(code) == 1
                and 1 <= len(code[0]) <= 256
                and code[0].isascii()
                and code[0].isalnum()
                and not received
            )
            self.send_response(200 if valid else 403)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if valid:
                received.append(code[0])
                self.wfile.write(b"Return to the terminal to finish setup. You can close this tab.")
            else:
                self.wfile.write(b"Invalid or expired registration callback.")

    return Callback


@command("github-app-setup", help="Register a customer-owned GitHub App from a read-only manifest")
@click.option("--base-url", required=True, help="Your AgenticOS HTTPS origin, reachable by GitHub.")
@click.option(
    "--org", "organization_id", required=True, type=click.UUID, help="AgenticOS organization UUID."
)
@click.option("--name", required=True, help="App/Vault name, at most 34 characters.")
@click.option(
    "--github-org",
    default=None,
    help="GitHub organization owning the app; omit for your personal account.",
)
@click.option(
    "--event",
    "events",
    multiple=True,
    type=click.Choice(list(EVENT_PERMISSIONS)),
    help="Repeat to select events; default is all six read-only trigger events.",
)
@click.option(
    "--access-token-file",
    type=click.File("r", encoding="utf-8"),
    default=None,
    help="Protected AgenticOS access-token file; omit for hidden input.",
)
@click.option(
    "--callback-port",
    default=0,
    type=click.IntRange(0, 65535),
    help="Loopback callback port; 0 chooses an unused port. Use a fixed port for an SSH forward.",
)
@click.option("--timeout", default=900, type=click.IntRange(30, 3600), show_default=True)
def github_app_setup(
    base_url: str,
    organization_id: UUID,
    name: str,
    github_org: str | None,
    events: tuple[str, ...],
    access_token_file: TextIO | None,
    timeout: int,
    callback_port: int,
) -> None:
    """Run on the browser's own machine. No app secrets are written to files."""
    try:
        origin = https_origin(base_url)
        token = (
            access_token_file.read(8193)
            if access_token_file
            else click.prompt(
                "AgenticOS access token (secrets:view + secrets:edit)", hide_input=True
            ).strip()
        )
        if access_token_file is not None and len(token) > 8192:
            raise click.UsageError("The access-token file exceeds 8192 characters.")
        token = token.strip()
        if (
            not token
            or len(token) > 8192
            or not token.isascii()
            or "\x00" in token
            or any(char.isspace() for char in token)
        ):
            raise click.UsageError("Use a valid access token without whitespace.")
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            preflight_registration(
                client,
                base_url=origin,
                organization_id=organization_id,
                access_token=SecretStr(token),
                name=name,
            )
        received: list[str] = []
        state = secrets.token_hex(32)
        with HTTPServer(("127.0.0.1", callback_port), _handler(state, received)) as server:
            callback = f"http://127.0.0.1:{server.server_port}/callback"
            manifest = manifest_for(
                base_url=origin,
                name=name,
                callback_url=callback,
                events=events or tuple(EVENT_PERMISSIONS),
            )
            form = registration_form(manifest, state=state, owner=github_org)
            with TemporaryDirectory(prefix="agenticos-github-app-") as directory:
                path = Path(directory) / "register.html"
                path.write_text(form, encoding="utf-8")
                path.chmod(0o600)
                click.echo(f"Callback listener: {callback}")
                click.echo(f"Open this file in your browser and approve registration: {path}")
                code = _wait_for_code(server, received, timeout=timeout)
            registration = _convert(code)
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            secret_id = store_registration(
                client,
                registration=registration,
                base_url=origin,
                organization_id=organization_id,
                access_token=SecretStr(token),
                name=manifest["name"],
            )
        click.echo(f"GitHub App credentials stored in the organization Vault: {secret_id}")
        click.echo(
            f"Install only on chosen repositories: https://github.com/apps/{registration.slug}/installations/new"
        )
        click.echo("Then connect GitHub (App) in AgenticOS using its installation ID.")
    except AppException as exc:
        raise click.ClickException(
            exc.message
            + ". If an app was created, inspect GitHub App settings and Vault before retrying."
        ) from None
    except OSError, UnicodeError:
        raise click.ClickException(
            "Cannot read setup input or bind the loopback callback."
        ) from None
