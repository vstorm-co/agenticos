"""Exercise verified HTTPS, console authentication and WSS through local CRC Routes."""

import asyncio

from oidc_probe import client
from smoke_probe import mapping, rows, text
from websockets.asyncio.client import connect

SITE = "https://app-agenticos-smoke.apps-crc.testing"
API = "https://api-agenticos-smoke.apps-crc.testing"


async def websocket(token: str, organization: str) -> None:
    import ssl
    from pathlib import Path

    trust = ssl.create_default_context()
    trust.load_verify_locations(cafile=Path(__file__).with_name("router-ca.crt"))
    async with connect(
        f"wss://api-agenticos-smoke.apps-crc.testing/api/v1/ws/events?organization_id={organization}",
        ssl=trust,
        subprotocols=["agenticos", "access_token." + token],
        open_timeout=30,
    ) as socket:
        assert socket.subprotocol == "agenticos"
        pong = await socket.ping()
        await asyncio.wait_for(pong, timeout=15)
    print("PASS authenticated WSS upgrade and ping through the OpenShift router", flush=True)


def main() -> None:
    with client() as browser:
        login = browser.post(
            SITE + "/api/auth/login",
            json={
                "email": "smoke@example.com",
                "password": "smoke-password-2872",
            },
        )
        assert login.status_code == 200, login.status_code
        token = text(mapping(login.json())["access_token"])
        cookies = [
            cookie
            for cookie in login.headers.get_list("set-cookie")
            if cookie.startswith(
                (
                    "agenticos_access_token=",
                    "agenticos_refresh_token=",
                )
            )
        ]
        assert len(cookies) == 2 and all(
            "Secure" in cookie and "HttpOnly" in cookie for cookie in cookies
        )
        organizations = browser.get(
            API + "/api/v1/orgs", headers={"Authorization": "Bearer " + token}
        )
        assert organizations.status_code == 200, organizations.status_code
        org = text(mapping(rows(mapping(organizations.json())["items"])[0])["id"])
        for path in ("/", "/login", "/agents", "/settings"):
            page = browser.get(SITE + path, follow_redirects=True)
            assert page.status_code == 200, (path, page.status_code)
        print(
            "PASS verified HTTPS Routes, BFF sign-in, Secure HttpOnly cookies and server page rendering",
            flush=True,
        )
        headers = {"Authorization": "Bearer " + token, "X-Organization-Id": org}
        content = b"OpenShift verified TLS upload and S3 download"
        uploaded = browser.post(
            API + "/api/v1/files/upload",
            headers=headers,
            files={"file": ("route-check.txt", content, "text/plain")},
        )
        assert uploaded.is_success, uploaded.status_code
        file_id = text(mapping(uploaded.json())["id"])
        downloaded = browser.get(API + "/api/v1/files/" + file_id, headers=headers)
        assert downloaded.status_code == 200 and downloaded.content == content
        print("PASS upload and byte-exact S3 download through verified HTTPS Routes", flush=True)
    asyncio.run(websocket(token, org))


if __name__ == "__main__":
    main()
