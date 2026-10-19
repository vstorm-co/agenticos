"""The public API's OpenAPI document (#1796).

Served in every environment, unlike `/openapi.json` and `/docs`: those describe
every route the console calls, which a production deployment keeps to itself,
while this one is the contract an integration is written against - and an
integrator needs it from the deployment they integrate with.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.openapi.utils import get_openapi

from app.api.public_api import PUBLIC_OPENAPI_PATH, public_openapi, public_operations

router = APIRouter()


@router.get(PUBLIC_OPENAPI_PATH, include_in_schema=False)
async def get_public_openapi(request: Request) -> Any:
    """The OpenAPI document of the routes an organization API key may call."""
    cached = getattr(request.app.state, "public_openapi", None)
    if cached is None:
        app = request.app
        full = get_openapi(
            title=f"{app.title} public API",
            version=app.version,
            routes=app.routes,
            separate_input_output_schemas=app.separate_input_output_schemas,
        )
        cached = public_openapi(full, public_operations(app.routes))
        request.app.state.public_openapi = cached
    return cached
