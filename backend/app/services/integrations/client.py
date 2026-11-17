"""Bounded provider transport: credentials only reach code-owned endpoints."""

from urllib.parse import quote

import httpx
from pydantic import JsonValue, SecretStr, TypeAdapter, ValidationError
from pydantic_ai._ssrf import safe_download

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.services.integrations.catalog import Operation
from app.services.integrations.files import file_text, upload_bytes, word_bytes

_JSON = TypeAdapter(dict[str, JsonValue])
_MAX_RESPONSE_BYTES = 2_000_000


async def execute(
    operation: Operation,
    token: SecretStr,
    *,
    parameters: dict[str, str],
    query: dict[str, str],
    body: dict[str, JsonValue] | None,
) -> dict[str, JsonValue]:
    """Execute one declared operation, without retrying potentially committed writes.

    Path segments are encoded individually. Redirects are deliberately refused:
    the account's bearer token must never follow a provider-controlled Location.
    """
    if set(parameters) != set(operation.parameters) or not set(query) <= set(operation.query):
        raise BadRequestError(message="Use only the parameters declared by this integration tool")
    if any(not value or value in {".", ".."} or len(value) > 2000 for value in parameters.values()):
        raise BadRequestError(
            message="Integration identifiers must be nonempty and at most 2000 characters"
        )
    url = operation.url.format_map(
        {key: quote(value, safe="") for key, value in parameters.items()}
    )
    parsed_url = httpx.URL(url)
    query = {**dict(parsed_url.params), **query}
    url = str(parsed_url.copy_with(query=None))
    content_body: bytes | None = None
    headers = {"Authorization": f"Bearer {token.get_secret_value()}", "Accept": "application/json"}
    limit = _MAX_RESPONSE_BYTES if operation.response_format == "json" else 20_000_000
    if operation.encoding in {"base64", "drive_multipart"}:
        content_body, content_type, metadata = upload_bytes(body)
        body = None
        headers["Content-Type"] = content_type
        if operation.encoding == "drive_multipart":
            import secrets

            boundary = "agenticos-" + secrets.token_hex(24)
            content_body = (
                b"--"
                + boundary.encode()
                + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                + metadata
                + b"\r\n--"
                + boundary.encode()
                + b"\r\nContent-Type: "
                + content_type.encode()
                + b"\r\n\r\n"
                + content_body
                + b"\r\n--"
                + boundary.encode()
                + b"--"
            )
            headers["Content-Type"] = f"multipart/related; boundary={boundary}"
    elif operation.encoding == "word":
        if not parameters.get("filename", "").lower().endswith(".docx"):
            raise BadRequestError(message="A Word document filename must end in .docx")
        content_body = word_bytes(body)
        body = None
        headers["Content-Type"] = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    try:
        async with (
            httpx.AsyncClient(timeout=20, follow_redirects=False) as client,
            client.stream(
                operation.method,
                url,
                params=query,
                json=body,
                content=content_body,
                headers=headers,
            ) as response,
        ):
            if operation.response_format != "json" and response.is_redirect:
                target = response.headers.get("location", "")
                try:
                    # A pre-authenticated provider URL is downloaded with no account
                    # header. Every hop is pinned and checked for SSRF by the library.
                    downloaded = await safe_download(target, max_redirects=5, max_bytes=limit)
                except ValueError, httpx.HTTPError:
                    raise ExternalServiceError(
                        message="The provider's file download could not be completed"
                    ) from None
                return file_text(
                    downloaded.content,
                    downloaded.headers.get("content-type", "application/octet-stream"),
                    word=operation.response_format == "word",
                )
            response_type = response.headers.get("content-type", "application/octet-stream")
            if not 200 <= response.status_code < 300:
                raise ExternalServiceError(
                    message="The integration refused this operation; check the account and granted permissions",
                    details={"status": response.status_code, "operation": operation.id},
                )
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > limit:
                    raise ExternalServiceError(
                        message="The integration response is too large; narrow the request"
                    )
    except httpx.HTTPError as exc:
        raise ExternalServiceError(
            message="The integration could not be reached; a write may already have completed",
            details={"operation": operation.id},
        ) from exc
    if not content:
        return {}
    if operation.response_format != "json":
        return file_text(bytes(content), response_type, word=operation.response_format == "word")
    try:
        result = _JSON.validate_json(content)
    except ValidationError as exc:
        raise ExternalServiceError(
            message="The integration returned an unreadable response"
        ) from exc
    if operation.url.startswith("https://slack.com/") and result.get("ok") is not True:
        raise ExternalServiceError(
            message="Slack refused this operation; check the account and granted scopes"
        )
    return result
