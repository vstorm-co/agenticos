"""Exercise a real local Keycloak authorization-code flow from the API pod.

The provider, users and passwords are disposable validation fixtures. Run only in
an isolated test deployment after importing the matching Keycloak realm.
"""

import ssl
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from smoke_probe import mapping, rows, text

BASE = "https://api-agenticos-smoke.apps-crc.testing/api/v1"
PASSWORD = "local-oidc-validation-password"


def client() -> httpx.Client:
    trust = ssl.create_default_context()
    trust.load_verify_locations(cafile=Path(__file__).with_name("router-ca.crt"))
    return httpx.Client(timeout=60, follow_redirects=False, verify=trust)


class LoginForm(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self.action = attributes.get("action")
        if tag == "input" and attributes.get("type") == "hidden":
            name = attributes.get("name")
            if name:
                self.fields[name] = attributes.get("value") or ""


def sign_in(username: str, *, admitted: bool) -> None:
    with client() as browser:
        start = browser.get(f"{BASE}/oauth/oidc/login")
        assert start.status_code in {302, 307}, start.status_code
        authorization = start.headers["location"]
        query = parse_qs(urlsplit(authorization).query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["code_challenge"][0]
        login = browser.get(authorization)
        assert login.status_code == 200, login.status_code
        form = LoginForm()
        form.feed(login.text)
        assert form.action, "Keycloak login form is absent"
        approved = browser.post(
            form.action, data={**form.fields, "username": username, "password": PASSWORD}
        )
        assert approved.status_code in {302, 303}, approved.status_code
        callback = approved.headers["location"]
        assert urlsplit(callback).netloc == urlsplit(BASE).netloc, (
            "Unexpected authorization redirect host"
        )
        handoff = browser.get(callback)
        assert handoff.status_code in {302, 307}, handoff.status_code
        target = urlsplit(handoff.headers["location"])
        parameters = parse_qs(target.query)
        if not admitted:
            assert target.path == "/login" and "error" in parameters, "Expected OIDC refusal"
            return
        assert target.path == "/auth/callback" and "code" in parameters, (
            "Expected console code handoff"
        )
        code = parameters["code"][0]
        exchanged = browser.post(f"{BASE}/oauth/exchange", json={"code": code})
        assert exchanged.status_code == 200, exchanged.status_code
        tokens = mapping(exchanged.json())
        assert browser.post(f"{BASE}/oauth/exchange", json={"code": code}).status_code == 401
        headers = {"Authorization": "Bearer " + text(tokens["access_token"])}
        me = browser.get(f"{BASE}/auth/me", headers=headers)
        assert me.status_code == 200, me.status_code
        assert mapping(me.json())["email"] == f"{username}@allowed.example"
        organizations = browser.get(f"{BASE}/orgs", headers=headers)
        assert organizations.status_code == 200 and rows(mapping(organizations.json())["items"])
        logout = browser.post(
            f"{BASE}/auth/logout", json={"refresh_token": tokens["refresh_token"]}
        )
        assert logout.status_code == 204, logout.status_code
        refreshed = browser.post(
            f"{BASE}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refreshed.status_code == 401, refreshed.status_code


def main() -> None:
    with client() as administrator:
        login = administrator.post(
            f"{BASE}/auth/login",
            data={"username": "smoke@example.com", "password": "smoke-password-2872"},
        )
        assert login.status_code == 200, login.status_code
        administrator.headers["Authorization"] = "Bearer " + text(
            mapping(login.json())["access_token"]
        )
        current = administrator.get(f"{BASE}/admin/settings")
        assert current.status_code == 200, current.status_code
        settings = mapping(current.json())
        original = {key: settings[key] for key in ("signup_mode", "allowed_email_domains")}
        try:
            updated = administrator.patch(
                f"{BASE}/admin/settings", json={"signup_mode": "open", "allowed_email_domains": []}
            )
            assert updated.status_code == 200, updated.status_code
            sign_in("verified", admitted=True)
            print(
                "PASS Keycloak discovery, PKCE, signed token, console code exchange, identity and organization access"
            )
            print("PASS one-use exchange code and logout/refresh revocation")
            sign_in("unverified", admitted=False)
            print("PASS unverified OIDC email refusal")
            updated = administrator.patch(
                f"{BASE}/admin/settings", json={"allowed_email_domains": ["allowed.example"]}
            )
            assert updated.status_code == 200, updated.status_code
            sign_in("outside", admitted=False)
            print("PASS OIDC domain policy refusal")
            updated = administrator.patch(
                f"{BASE}/admin/settings", json={"signup_mode": "invite_only"}
            )
            assert updated.status_code == 200, updated.status_code
            sign_in("uninvited", admitted=False)
            print("PASS OIDC invite-only refusal")
        finally:
            restored = administrator.patch(f"{BASE}/admin/settings", json=original)
            assert restored.status_code == 200, restored.status_code


if __name__ == "__main__":
    main()
