"""A GitHub App instead of an OAuth App with `admin:repo_hook` (#1072).

The OAuth App path works and is not going anywhere; what it costs is the reason
for this one. `repo` plus `admin:repo_hook` is read-write on every repository the
*person* can administer, the token never expires, and a hook has to be created
and deleted per repository. An App is installed on the repositories somebody
chose, its token lives an hour, and it is already delivering.

The trade is that the URL stops naming the trigger: one App, one webhook URL, one
signing secret per installation. So everything worth testing here is the routing
that replaces it - which grant a delivery belongs to, which triggers it fires,
and what a delivery nobody claims is answered with.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.secret_kinds import GithubAppSecret
from app.services.agent_trigger import AgentTriggerService
from app.services.portals.github_app import (
    GitHubAppPortalAdapter,
    InstallationTokens,
    app_jwt,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]

SERVICE = "app.services.agent_trigger"
ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()
INSTALLATION = "42"
SECRET = "the-app-webhook-secret"

# Generated once for the suite: RS256 needs a real key and a fixture is cheaper
# than asking `cryptography` to make one per test.
_KEY: str | None = None


def _private_key() -> str:
    global _KEY
    if _KEY is None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        _KEY = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
    return _KEY


def _body(*, repo: str = "acme/widgets", action: str = "opened") -> bytes:
    return json.dumps(
        {
            "installation": {"id": int(INSTALLATION)},
            "repository": {"full_name": repo},
            "action": action,
            "issue": {"number": 7, "title": "It broke", "body": "here is how"},
        }
    ).encode()


def _headers(body: bytes, *, secret: str = SECRET, event: str = "issues") -> dict[str, str]:
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "x-hub-signature-256": signature,
        "x-github-event": event,
        "x-github-delivery": str(uuid.uuid4()),
    }


def _grant(organization_id: uuid.UUID = ORG) -> SimpleNamespace:
    return SimpleNamespace(organization_id=organization_id, portal_account_id=INSTALLATION)


def _trigger(
    *, target: str = "acme/widgets", portal_key: str = "github_app", actions=("opened",)
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        portal_key=portal_key,
        provider_target=target,
        event_config={"actions": list(actions)},
    )


#: A stand-in for the PEM, assembled rather than written out.
#:
#: `detect-private-key` in the pre-commit hooks greps for the header line, and it
#: is right to: a test fixture that reads like a key is indistinguishable from one
#: until somebody looks. Nothing here signs with it - `_private_key()` generates a
#: real one for the two tests that do.
_NOT_A_KEY = "-----BEGIN " + "PRIVATE KEY" + "-----\nnot a key\n"


def _secret(webhook_secret: str = SECRET) -> GithubAppSecret:
    return GithubAppSecret(
        app_id="123456",
        private_key=SecretStr(_NOT_A_KEY),
        webhook_secret=SecretStr(webhook_secret),
    )


def _scope(organization_id: uuid.UUID):
    from app.core.vault import VaultScope

    return VaultScope.organization(organization_id)


def _service() -> AgentTriggerService:
    db = MagicMock()
    db.execute = AsyncMock()
    return AgentTriggerService(db)


def _wired(*, grants=(), triggers=(), secret=None, claims=True):
    """Patch the four things a delivery touches, as one context manager stack."""
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(
        patch(
            f"{SERVICE}.mcp_connection_repo.portal_grants_for_account",
            new=AsyncMock(return_value=list(grants)),
        )
    )
    stack.enter_context(
        patch(
            f"{SERVICE}.agent_trigger_repo.list_active_for_event_source",
            new=AsyncMock(return_value=list(triggers)),
        )
    )
    stack.enter_context(
        patch(
            "app.services.organization_secret.OrganizationSecretService.app_secret",
            new=AsyncMock(
                return_value=secret if secret is not None else _secret(),
                side_effect=None if secret is not False else NotFoundError(message="none stored"),
            ),
        )
    )
    stack.enter_context(
        patch(
            f"{SERVICE}.trigger_dedupe.claim_event_delivery",
            new=AsyncMock(return_value=claims),
        )
    )
    return stack


class TestWhoseDeliveryItIs:
    async def test_the_signature_settles_it_not_the_installation_id(self) -> None:
        """The installation id selects candidates and authorises nothing; two
        organizations could hold grants the provider numbered the same, and
        answering the first would hand one of them the other's deliveries."""
        body = _body()
        theirs = _secret("someone-elses-secret")
        with _wired(grants=[_grant(OTHER_ORG)], secret=theirs), pytest.raises(AuthorizationError):
            await _service().prepare_app_fires(body=body, headers=_headers(body))

    async def test_a_delivery_signed_by_a_known_installation_is_routed(self) -> None:
        body = _body()
        trigger = _trigger()
        with _wired(grants=[_grant()], triggers=[trigger]):
            decisions = await _service().prepare_app_fires(body=body, headers=_headers(body))

        assert [decision.trigger_id for decision in decisions] == [trigger.id]

    async def test_an_installation_nobody_holds_a_grant_for_is_refused(self) -> None:
        """No candidate can have signed it, so it did not verify - and a 403 is
        how GitHub surfaces a misconfigured App to its integrator."""
        body = _body()
        with _wired(grants=[]), pytest.raises(AuthorizationError):
            await _service().prepare_app_fires(body=body, headers=_headers(body))

    async def test_an_organization_with_no_app_secret_stored_is_skipped(self) -> None:
        """Its grant cannot have signed this, and a delivery is not the place to
        tell somebody their vault is incomplete."""
        body = _body()
        with _wired(grants=[_grant()], secret=False), pytest.raises(AuthorizationError):
            await _service().prepare_app_fires(body=body, headers=_headers(body))

    async def test_a_payload_with_no_installation_fires_nothing_quietly(self) -> None:
        """A ping, or an event shape this App does not handle. Not a refusal:
        nothing claims it, and nothing is wrong."""
        body = json.dumps({"zen": "Non-blocking is better than blocking."}).encode()
        with _wired(grants=[_grant()]):
            assert await _service().prepare_app_fires(body=body, headers=_headers(body)) == []


class TestWhichTriggersFire:
    async def test_one_delivery_can_fire_several(self) -> None:
        """The per-trigger URL cannot do this by construction, and two triggers on
        one repository is exactly what the presets invite."""
        body = _body()
        first, second = _trigger(), _trigger()
        with _wired(grants=[_grant()], triggers=[first, second]):
            decisions = await _service().prepare_app_fires(body=body, headers=_headers(body))

        assert [decision.trigger_id for decision in decisions] == [first.id, second.id]

    async def test_a_trigger_on_another_repository_is_not_fired(self) -> None:
        body = _body(repo="acme/widgets")
        with _wired(grants=[_grant()], triggers=[_trigger(target="acme/other")]):
            assert await _service().prepare_app_fires(body=body, headers=_headers(body)) == []

    async def test_an_oauth_app_trigger_is_not_fired_by_an_app_delivery(self) -> None:
        """The two paths coexist, and a trigger registered as a repository hook
        already gets its own delivery at its own URL - firing it here as well
        would double every run."""
        body = _body()
        with _wired(grants=[_grant()], triggers=[_trigger(portal_key="github")]):
            assert await _service().prepare_app_fires(body=body, headers=_headers(body)) == []

    async def test_an_action_the_filter_excludes_is_not_fired(self) -> None:
        body = _body(action="closed")
        with _wired(grants=[_grant()], triggers=[_trigger(actions=("opened",))]):
            assert await _service().prepare_app_fires(body=body, headers=_headers(body)) == []

    async def test_a_redelivery_fires_nothing_twice(self) -> None:
        body = _body()
        with _wired(grants=[_grant()], triggers=[_trigger()], claims=False):
            assert await _service().prepare_app_fires(body=body, headers=_headers(body)) == []

    async def test_a_delivery_with_no_repository_fires_nothing(self) -> None:
        body = json.dumps({"installation": {"id": int(INSTALLATION)}, "action": "opened"}).encode()
        with _wired(grants=[_grant()], triggers=[_trigger()]):
            assert await _service().prepare_app_fires(body=body, headers=_headers(body)) == []


class TestTheAppsOwnCredentials:
    def test_the_assertion_is_signed_with_the_private_key_and_expires(self) -> None:
        """It authenticates the App, not an installation: all it can do is read
        the App's metadata and mint a token, which is what lets the long-lived
        credential be a key that grants nothing by itself."""
        import jwt

        token = app_jwt(app_id="123456", private_key=_private_key(), now=1_000_000)
        claims = jwt.decode(token, options={"verify_signature": False})

        assert claims["iss"] == "123456"
        # Backdated a minute for a clock behind GitHub's, and inside their
        # ten-minute ceiling for one ahead.
        assert claims["iat"] == 1_000_000 - 60
        assert 0 < claims["exp"] - 1_000_000 <= 600

    def test_a_token_is_reused_until_it_is_nearly_stale(self) -> None:
        """A cache that did not exist would mint one per delivery, and GitHub
        rate-limits the minting endpoint like any other."""
        from app.services.portals.github_app import InstallationToken

        tokens = InstallationTokens()
        tokens.remember("42", InstallationToken(token="ghs_x", expires_at=1_000.0))

        assert tokens.cached("42", now=900.0) == "ghs_x"
        # Inside the skew, so it is treated as gone rather than handed out to a
        # request that would reach GitHub after it expired.
        assert tokens.cached("42", now=950.0) is None

    def test_an_unknown_installation_has_nothing_cached(self) -> None:
        assert InstallationTokens().cached("99") is None

    def test_a_refused_token_is_forgotten(self) -> None:
        from app.services.portals.github_app import InstallationToken

        tokens = InstallationTokens()
        tokens.remember("42", InstallationToken(token="ghs_x", expires_at=1e12))
        tokens.forget("42")

        assert tokens.cached("42") is None


class TestWhatTheAdapterRegisters:
    async def test_it_registers_no_hook_and_says_so_by_answering(self) -> None:
        """An App already receives its installation's events. Raising the base
        class's `WebhookRegistrationUnavailable` would degrade the create flow to
        manual and ask somebody to paste a URL into a repository that is already
        delivering."""
        registered = await GitHubAppPortalAdapter().register_webhook(
            access_token="ghs_x",
            target="acme/widgets",
            webhook_url="https://example.com/hook",
            secret="s",
        )

        assert registered.provider_webhook_id == ""


class TestMintingAnInstallationToken:
    """The hour-long credential, and what happens when GitHub will not mint one."""

    @staticmethod
    def _responding(handler):
        import httpx

        from app.services.portals import github_app as module

        real = httpx.AsyncClient

        def client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real(*args, **kwargs)

        return patch.object(module.httpx, "AsyncClient", client)

    async def test_a_minted_token_is_returned_and_cached(self, monkeypatch) -> None:
        from app.services.portals import github_app as module

        monkeypatch.setattr(module, "TOKENS", InstallationTokens())
        import httpx

        with self._responding(lambda request: httpx.Response(201, json={"token": "ghs_new"})):
            token = await module.installation_token(
                app_id="1",
                private_key=_private_key(),
                installation_id="42",
                now=1_000.0,
            )

        assert token == "ghs_new"
        # And the next caller does not mint a second one.
        assert module.TOKENS.cached("42", now=1_100.0) == "ghs_new"

    async def test_a_cached_token_costs_no_request(self, monkeypatch) -> None:
        from app.services.portals import github_app as module
        from app.services.portals.github_app import InstallationToken

        cache = InstallationTokens()
        cache.remember("42", InstallationToken(token="ghs_held", expires_at=1e12))
        monkeypatch.setattr(module, "TOKENS", cache)

        def refuse(request):  # pragma: no cover - the point is that it is not called
            raise AssertionError("a cached token should not reach GitHub")

        with self._responding(refuse):
            token = await module.installation_token(
                app_id="1", private_key=_private_key(), installation_id="42"
            )

        assert token == "ghs_held"

    async def test_a_refusal_is_a_provider_failure_naming_no_body(self, monkeypatch) -> None:
        """GitHub's body may name the App; the refusal names neither, like every
        provider refusal here."""
        import httpx

        from app.services.portals import github_app as module
        from app.services.portals.exceptions import PortalUnreachable

        monkeypatch.setattr(module, "TOKENS", InstallationTokens())
        with (
            self._responding(lambda request: httpx.Response(403, json={"message": "no"})),
            pytest.raises(PortalUnreachable),
        ):
            await module.installation_token(
                app_id="1", private_key=_private_key(), installation_id="42"
            )

    async def test_an_unreachable_github_is_a_provider_failure(self, monkeypatch) -> None:
        import httpx

        from app.services.portals import github_app as module
        from app.services.portals.exceptions import PortalUnreachable

        monkeypatch.setattr(module, "TOKENS", InstallationTokens())

        def drop(request):
            raise httpx.ConnectError("no route")

        with self._responding(drop), pytest.raises(PortalUnreachable):
            await module.installation_token(
                app_id="1", private_key=_private_key(), installation_id="42"
            )


class TestListingWhatWasInstalledOn:
    """Not every repository the person administers - the ones somebody chose."""

    @staticmethod
    def _responding(handler):
        import httpx

        from app.services.portals import github_app as module

        real = httpx.AsyncClient

        def client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real(*args, **kwargs)

        return patch.object(module.httpx, "AsyncClient", client)

    async def test_it_lists_the_installations_repositories(self) -> None:
        import httpx

        body = {"repositories": [{"full_name": "acme/widgets"}, {"full_name": "acme/docs"}]}
        with self._responding(lambda request: httpx.Response(200, json=body)):
            targets = await GitHubAppPortalAdapter().list_preset_targets(access_token="ghs_x")

        assert [target.id for target in targets] == ["acme/widgets", "acme/docs"]

    async def test_it_follows_pages_until_one_comes_back_short(self) -> None:
        import httpx

        pages = [
            {"repositories": [{"full_name": f"acme/repo-{index}"} for index in range(100)]},
            {"repositories": [{"full_name": "acme/last"}]},
        ]
        seen: list[int] = []

        def handler(request):
            page = int(request.url.params["page"])
            seen.append(page)
            return httpx.Response(200, json=pages[page - 1])

        with self._responding(handler):
            targets = await GitHubAppPortalAdapter().list_preset_targets(access_token="ghs_x")

        assert seen == [1, 2]
        assert targets[-1].id == "acme/last"

    async def test_it_stops_at_the_page_cap(self) -> None:
        """A thousand repositories in one installation is past what a select is
        good for, and the cap is what keeps a listing bounded rather than
        following pages until GitHub runs out."""
        import httpx

        full = {"repositories": [{"full_name": f"acme/repo-{index}"} for index in range(100)]}
        seen: list[int] = []

        def handler(request):
            seen.append(int(request.url.params["page"]))
            return httpx.Response(200, json=full)

        with self._responding(handler):
            targets = await GitHubAppPortalAdapter().list_preset_targets(access_token="ghs_x")

        assert seen == list(range(1, 11))
        assert len(targets) == 1000

    async def test_a_refusal_stops_the_listing_rather_than_raising(self) -> None:
        """The dialog falls back to free-text entry; a 500 would take the form
        down over a permission the installation simply does not have."""
        import httpx

        with self._responding(lambda request: httpx.Response(403, json={})):
            assert await GitHubAppPortalAdapter().list_preset_targets(access_token="ghs_x") == []

    async def test_an_unreachable_github_is_a_provider_failure(self) -> None:
        import httpx

        from app.services.portals.exceptions import PortalUnreachable

        def drop(request):
            raise httpx.ConnectError("no route")

        with self._responding(drop), pytest.raises(PortalUnreachable):
            await GitHubAppPortalAdapter().list_preset_targets(access_token="ghs_x")


class TestTheStoredCredential:
    def test_the_hint_is_the_app_id_not_the_key(self) -> None:
        """It names the App on the settings page the key sits next to, and it is
        the one field of the three that is not a secret."""
        assert _secret().hint == "3456"

    async def test_the_organizations_app_is_read_by_id_with_no_caller(self) -> None:
        """A delivery has no session, and the organization is already established
        - it is the one holding the grant the installation id selected."""
        from app.core.secret_kinds import SecretKind, seal_secret
        from app.services.organization_secret import OrganizationSecretService

        sealed = seal_secret(_secret(), scope=_scope(ORG))
        row = SimpleNamespace(sealed_secret=sealed.ciphertext, key_version=sealed.key_version)
        service = OrganizationSecretService(MagicMock())
        with patch(
            "app.services.organization_secret.organization_secret_repo.list_org_visible_by_kind",
            new=AsyncMock(return_value=[row]),
        ):
            found = await service.app_secret(ORG, kind=SecretKind.GITHUB_APP)

        assert isinstance(found, GithubAppSecret)
        assert found.webhook_secret.get_secret_value() == SECRET

    async def test_none_stored_is_not_found(self) -> None:
        from app.core.secret_kinds import SecretKind
        from app.services.organization_secret import OrganizationSecretService

        service = OrganizationSecretService(MagicMock())
        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.list_org_visible_by_kind",
                new=AsyncMock(return_value=[]),
            ),
            pytest.raises(NotFoundError),
        ):
            await service.app_secret(ORG, kind=SecretKind.GITHUB_APP)

    async def test_two_stored_is_refused_by_name(self) -> None:
        """Silently taking whichever sorts first would key the deliveries to a
        credential nobody chose."""
        from app.core.exceptions import BadRequestError
        from app.core.secret_kinds import SecretKind
        from app.services.organization_secret import OrganizationSecretService

        rows = [SimpleNamespace(name="one"), SimpleNamespace(name="two")]
        service = OrganizationSecretService(MagicMock())
        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.list_org_visible_by_kind",
                new=AsyncMock(return_value=rows),
            ),
            pytest.raises(BadRequestError) as refusal,
        ):
            await service.app_secret(ORG, kind=SecretKind.GITHUB_APP)

        assert refusal.value.details["names"] == ["one", "two"]
