"""What this deployment calls itself - readable by anybody, and the bytes with it.

Unauthenticated on purpose, and the reason is structural rather than a
convenience: the favicon is served above every tenant, the sign-in page renders
before a session exists, and a maintenance page has to be able to say why the
deployment is closed. A surface that could not read this could not draw its own
name.

What that costs is bounded by what is in the response - the installation's name,
tagline, wordmark, whose terms it links to, whether registration is open, and
whether it is in a maintenance window. Every one of those is something a stranger
loading the login screen would see anyway. The announcement is **not** here: it is
written for the people using the deployment, so it sits behind a session in
`/notice`.

No rate limit, deliberately. The frontend server fetches this itself to render a
document - a favicon, a title, a login header - so what would arrive here is one
container's address, and counting it would put every visitor in the world in one
deployment-wide bucket. It is a single indexed-by-nothing read of one row.
"""

from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DeploymentSettingsSvc
from app.api.routes.v1._branding_bytes import serve_branding_image
from app.schemas.deployment_settings import BrandingRead, NoticeRead

router = APIRouter()


@router.get("", response_model=BrandingRead)
async def get_branding(service: DeploymentSettingsSvc) -> Any:
    """This deployment's identity and access policy, for any caller."""
    return await service.branding()


@router.get("/notice", response_model=NoticeRead)
async def get_notice(service: DeploymentSettingsSvc, _user: CurrentUser) -> Any:
    """The announcement banner, if the administrator has written one.

    Behind a session, unlike the rest of this router. An announcement is an
    operator talking to the people who use the deployment - an upgrade window, who
    to ping - and there is no reason for a stranger on the sign-in page to read it.
    """
    return await service.notice()


@router.get("/logo", response_class=FileResponse)
async def get_logo(service: DeploymentSettingsSvc) -> Any:
    """The uploaded wordmark, or 404 when the built-in mark is in use."""
    return await serve_branding_image(service, "logo")


@router.get("/favicon", response_class=FileResponse)
async def get_favicon(service: DeploymentSettingsSvc) -> Any:
    """The uploaded browser-tab icon, or 404 when the built-in one is in use."""
    return await serve_branding_image(service, "favicon")
