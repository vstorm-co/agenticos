"""Provider setup data generated from the same operation scopes used at consent."""

import json
from urllib.parse import urlencode

from pydantic import BaseModel

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.services.integrations.catalog import PRODUCTS, Provider, application_scopes


class SetupProduct(BaseModel):
    id: str
    name: str
    read_scopes: list[str]
    write_scopes: list[str]
    application_read_scopes: list[str] = []
    application_write_scopes: list[str] = []
    application_supported: bool = False


class IntegrationSetup(BaseModel):
    provider: Provider
    identity_scopes: list[str] = []
    redirect_uri: str
    console_url: str
    secret_kind: str
    products: list[SetupProduct]
    enable_apis_command: str | None = None
    manifest_url: str | None = None


def setup_for(provider: Provider, *, write: bool = False) -> IntegrationSetup:
    if provider not in {"google", "microsoft", "slack"}:
        raise BadRequestError(message="Unknown integration provider")
    products = [p for p in PRODUCTS.values() if p.provider == provider]
    redirect = f"{settings.FRONTEND_URL.rstrip('/')}/api/me/mcp-connections/oauth/callback"
    result = IntegrationSetup(
        provider=provider,
        identity_scopes=["openid", "email"]
        if provider == "google"
        else ["openid", "profile", "offline_access", "User.Read"]
        if provider == "microsoft"
        else [],
        redirect_uri=redirect,
        console_url={
            "google": "https://console.cloud.google.com/apis/credentials",
            "microsoft": "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
            "slack": "https://api.slack.com/apps",
        }[provider],
        secret_kind=f"{provider}_oauth_app",
        products=[
            SetupProduct(
                id=p.id,
                name=p.name,
                application_supported=provider == "google"
                or any(application_scopes(p.id, op) for op in p.operations),
                application_read_scopes=sorted(
                    {
                        scopes[0]
                        for op in p.operations
                        if not op.side_effecting
                        if (
                            scopes := application_scopes(p.id, op)
                            if provider == "microsoft"
                            else op.scopes
                        )
                    }
                ),
                application_write_scopes=sorted(
                    {
                        scopes[0]
                        for op in p.operations
                        if op.side_effecting
                        if (
                            scopes := application_scopes(p.id, op)
                            if provider == "microsoft"
                            else op.scopes
                        )
                    }
                ),
                read_scopes=sorted(
                    {
                        scope
                        for op in p.operations
                        if not op.side_effecting
                        for scope in (op.scopes if provider == "slack" else op.scopes[:1])
                    }
                ),
                write_scopes=sorted(
                    {scope for op in p.operations if op.side_effecting for scope in op.scopes[:1]}
                ),
            )
            for p in products
        ],
    )
    if provider == "google":
        result.enable_apis_command = "gcloud services enable gmail.googleapis.com calendar-json.googleapis.com drive.googleapis.com docs.googleapis.com sheets.googleapis.com slides.googleapis.com"
    if provider == "slack":
        manifest = {
            "display_information": {"name": "AgenticOS"},
            "oauth_config": {
                "redirect_urls": [redirect],
                "scopes": {
                    "user": sorted(
                        set(
                            result.products[0].read_scopes
                            + (result.products[0].write_scopes if write else [])
                        )
                    )
                },
            },
            "settings": {"org_deploy_enabled": False, "socket_mode_enabled": False},
        }
        result.manifest_url = "https://api.slack.com/apps?" + urlencode(
            {"new_app": "1", "manifest_json": json.dumps(manifest, separators=(",", ":"))}
        )
    return result
