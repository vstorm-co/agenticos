"""A GitHub App: installed on chosen repositories, with a key that mints short tokens.

The OAuth App path still works and is still here. What it costs is the reason for
this one (#1072):

- **The token is scoped to the person, not the work.** `repo` plus
  `admin:repo_hook` is read-write on every repository the account can
  administer, so connecting one repository to one trigger hands the deployment a
  credential that can push to all of them. An App is installed on the
  repositories somebody chose, with the permissions the App declares.
- **The token never expires.** A classic OAuth App token has no refresh and no
  expiry, so a leaked one is valid until somebody revokes it by hand. An
  installation token lives an hour and is minted on demand from a private key
  that never leaves the vault.
- **A hook per repository.** Ten repositories is ten hooks to create, ten to
  delete, and ten chances for a 403 to degrade the flow to manual. An App
  receives its installation's events with no per-repository registration at all -
  which is why `register_webhook` here is a deliberate no-op rather than an
  unimplemented method.
- **The rate limit is the user's**, shared with everything else that account
  authorised. An App has its own.

**One App, one webhook URL, one signing secret**, which is what makes this a
second delivery mode rather than a second adapter with the same contract: the
URL cannot name a trigger, so the delivery is authenticated once and then routed
by installation, repository and event. `app/services/agent_trigger.py` does the
routing; this module is the credential half.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
import jwt

from app.services.portals.base import PortalAdapter, PortalTarget, RegisteredWebhook
from app.services.portals.exceptions import PortalUnreachable

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_TIMEOUT = httpx.Timeout(10.0)
_MAX_REPO_PAGES = 10

#: How long the JWT that mints installation tokens is valid for.
#:
#: GitHub refuses one older than ten minutes. Nine leaves room for a clock a
#: little ahead of theirs without the request being rejected for expiry, and
#: `iat` is backdated a minute for a clock a little behind - the two failures a
#: self-hosted deployment actually hits.
_JWT_TTL_SECONDS = 9 * 60
_JWT_BACKDATE_SECONDS = 60

#: How long before an installation token's own expiry it is refreshed.
#:
#: GitHub issues them for an hour. A minute of margin means a token handed out
#: here is still valid when the request using it reaches them.
_TOKEN_SKEW_SECONDS = 60


@dataclass(frozen=True)
class InstallationToken:
    """A minted token and when it stops working."""

    token: str
    expires_at: float


def app_jwt(*, app_id: str, private_key: str, now: float | None = None) -> str:
    """The RS256 assertion that authenticates the App itself.

    Signed with the private key, never sent anywhere but GitHub, and good for
    nine minutes. It authenticates the *App*, not an installation: the only
    things it can do are read the App's own metadata and mint an installation
    token, which is the whole reason the long-lived credential can be a key that
    grants nothing by itself.
    """
    issued = int(now if now is not None else time.time())
    return jwt.encode(
        {
            "iat": issued - _JWT_BACKDATE_SECONDS,
            "exp": issued + _JWT_TTL_SECONDS,
            "iss": app_id,
        },
        private_key,
        algorithm="RS256",
    )


class InstallationTokens:
    """Installation tokens, minted on demand and reused until they are nearly stale.

    In-process and per installation. A cache that lived in Redis would be a
    credential at rest outside the vault for an hour; a cache that did not exist
    would mint a token per delivery, and GitHub rate-limits the minting endpoint
    like any other. Worker and API each keep their own, which is correct - a
    token is valid wherever it is used.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, InstallationToken] = {}

    def cached(self, installation_id: str, *, now: float | None = None) -> str | None:
        """A token for this installation that is still comfortably valid, or None."""
        held = self._tokens.get(installation_id)
        moment = now if now is not None else time.time()
        if held is None or held.expires_at - _TOKEN_SKEW_SECONDS <= moment:
            return None
        return held.token

    def remember(self, installation_id: str, token: InstallationToken) -> None:
        self._tokens[installation_id] = token

    def forget(self, installation_id: str) -> None:
        """Drop a token the provider has refused, so the next call mints a fresh one."""
        self._tokens.pop(installation_id, None)


#: The process's cache. One per process, so nothing has to pass it around.
TOKENS = InstallationTokens()


async def installation_token(
    *, app_id: str, private_key: str, installation_id: str, now: float | None = None
) -> str:
    """A token that acts as this installation, from cache or freshly minted.

    Raises:
        PortalUnreachable: GitHub could not be asked, or refused the assertion.
            The caller treats it as it treats any provider failure - the grant is
            not wrong, the provider is not answering.
    """
    cached = TOKENS.cached(installation_id, now=now)
    if cached is not None:
        return cached

    assertion = app_jwt(app_id=app_id, private_key=private_key, now=now)
    try:
        async with httpx.AsyncClient(base_url=_API_BASE, timeout=_TIMEOUT) as client:
            response = await client.post(
                f"/app/installations/{installation_id}/access_tokens",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {assertion}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
    except httpx.HTTPError as exc:
        raise PortalUnreachable(
            message="GitHub could not be reached to mint an installation token",
            details={"portal_key": GitHubAppPortalAdapter.portal_key},
        ) from exc
    if response.status_code >= 400:
        # The body is GitHub's and may name the App; the refusal names neither,
        # for the same reason every provider refusal in this codebase does not.
        logger.warning("github_app_token_refused", extra={"status": response.status_code})
        raise PortalUnreachable(
            message="GitHub refused to mint an installation token for this App",
            details={"portal_key": GitHubAppPortalAdapter.portal_key},
        )
    body = response.json()
    token = InstallationToken(
        token=str(body["token"]),
        expires_at=(now if now is not None else time.time()) + 3600.0,
    )
    TOKENS.remember(installation_id, token)
    return token.token


class GitHubAppPortalAdapter(PortalAdapter):
    """The App's half of the portal contract: list repositories, register nothing."""

    portal_key = "github_app"

    async def list_preset_targets(self, *, access_token: str) -> list[PortalTarget]:
        """The repositories this installation was given, and only those.

        The difference from the OAuth adapter in one line: that one lists every
        repository the *person* can administer, this one lists what somebody
        deliberately installed the App on. `access_token` is an installation
        token here, which is why the contract did not have to change.
        """
        targets: list[PortalTarget] = []
        try:
            async with httpx.AsyncClient(base_url=_API_BASE, timeout=_TIMEOUT) as client:
                for page in range(1, _MAX_REPO_PAGES + 1):
                    response = await client.get(
                        "/installation/repositories",
                        headers={
                            "Accept": "application/vnd.github+json",
                            "Authorization": f"Bearer {access_token}",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
                        params={"per_page": 100, "page": page},
                    )
                    if response.status_code >= 400:
                        logger.warning(
                            "github_app_repos_refused", extra={"status": response.status_code}
                        )
                        break
                    found = response.json().get("repositories", [])
                    targets.extend(
                        PortalTarget(id=repo["full_name"], label=repo["full_name"])
                        for repo in found
                        if repo.get("full_name")
                    )
                    if len(found) < 100:
                        break
        except httpx.HTTPError as exc:
            raise PortalUnreachable(
                message="GitHub could not be reached to list this installation's repositories",
                details={"portal_key": self.portal_key},
            ) from exc
        return targets

    async def register_webhook(
        self, *, access_token: str, target: str | None, webhook_url: str, secret: str
    ) -> RegisteredWebhook:
        """Register nothing, and say so by answering rather than raising.

        An App already receives its installation's events. Raising
        `WebhookRegistrationUnavailable` here - the base class's behaviour - would
        degrade the create flow to manual and ask somebody to paste a URL into a
        repository that is already delivering. The empty id records that there is
        no provider-side hook to delete later.
        """
        return RegisteredWebhook(provider_webhook_id="")
