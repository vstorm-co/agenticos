"""Service-account and application grants reach only their provider's token endpoint."""

import time

import httpx
import jwt
from pydantic import BaseModel, SecretStr, ValidationError

from app.core.exceptions import ExternalServiceError
from app.core.secret_kinds import EntraAppSecret, GcpServiceAccountSecret


class GoogleKey(BaseModel):
    client_email: str
    private_key: SecretStr
    private_key_id: str | None = None


class AccessToken(BaseModel):
    access_token: SecretStr


async def _exchange(endpoint: str, form: dict[str, str]) -> SecretStr:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(endpoint, data=form)
        if not response.is_success:
            raise ExternalServiceError(
                message="The provider refused the integration credential; check the vault and administrator consent"
            )
        return AccessToken.model_validate_json(response.content).access_token
    except httpx.HTTPError, ValidationError:
        raise ExternalServiceError(
            message="The integration credential could not be exchanged"
        ) from None


async def google_token(
    key: GcpServiceAccountSecret, *, subject: str | None, scopes: list[str]
) -> SecretStr:
    try:
        document = GoogleKey.model_validate_json(key.service_account_json.get_secret_value())
    except ValidationError:
        raise ExternalServiceError(
            message="The Google service account credential is invalid; replace it in the vault"
        ) from None
    now = int(time.time())
    claims: dict[str, str | int] = {
        "iss": document.client_email,
        "scope": " ".join(scopes),
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    if subject:
        claims["sub"] = subject
    try:
        assertion = jwt.encode(
            claims,
            document.private_key.get_secret_value(),
            algorithm="RS256",
            headers={"kid": document.private_key_id} if document.private_key_id else None,
        )
    except ValueError, jwt.PyJWTError:
        raise ExternalServiceError(
            message="The Google service account key cannot sign an assertion; replace it in the vault"
        ) from None
    return await _exchange(
        "https://oauth2.googleapis.com/token",
        {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
    )


async def microsoft_token(app: EntraAppSecret) -> SecretStr:
    return await _exchange(
        f"https://login.microsoftonline.com/{app.tenant_id}/oauth2/v2.0/token",
        {
            "grant_type": "client_credentials",
            "client_id": app.client_id,
            "client_secret": app.client_secret.get_secret_value(),
            "scope": "https://graph.microsoft.com/.default",
        },
    )
