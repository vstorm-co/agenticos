"""The GitHub portal adapter - repository webhooks over GitHub's REST API.

GitHub cloud is a fixed host (`api.github.com`), so there is no SSRF surface here
to validate: the only URL we send is our own trigger endpoint, registered *at*
GitHub. The connected account's OAuth token (an MCP connection re-authorized for
`admin:repo_hook`) is what authorizes the hook; the platform mints the secret and
GitHub signs each delivery with it under `X-Hub-Signature-256`, which the delivery
layer already verifies.
"""

from __future__ import annotations

import logging

import httpx

from app.services.portals.base import PortalAdapter, PortalTarget, RegisteredWebhook
from app.services.portals.exceptions import PortalUnreachable, WebhookRegistrationForbidden

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_TIMEOUT = httpx.Timeout(10.0)
# The one webhook event the delivery layer acts on (`trigger_events._github_matches`
# refuses anything but `issues`), so every GitHub preset registers for it.
_EVENTS = ["issues"]
# How many 100-repo pages the target listing follows. Ten pages is a thousand
# administered repositories - past that the free-text target entry is the honest
# tool, and the cap is logged rather than silently truncating.
_MAX_REPO_PAGES = 10


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class GitHubPortalAdapter(PortalAdapter):
    portal_key = "github"

    async def list_preset_targets(self, *, access_token: str) -> list[PortalTarget]:
        """The repositories the account can administer - the ones a hook can be added to.

        Paginated to the cap above: the dialog offers a select whenever any
        targets come back, so a single-page fetch would make every repository
        past the first hundred unpickable even though the token administers it.
        """
        targets: list[PortalTarget] = []
        try:
            async with httpx.AsyncClient(base_url=_API_BASE, timeout=_TIMEOUT) as client:
                for page in range(1, _MAX_REPO_PAGES + 1):
                    resp = await client.get(
                        "/user/repos",
                        headers=_headers(access_token),
                        params={
                            "per_page": 100,
                            "page": page,
                            "affiliation": "owner,organization_member",
                        },
                    )
                    if resp.status_code != 200:
                        logger.warning(
                            "github_list_repos_failed", extra={"status": resp.status_code}
                        )
                        return []
                    rows = resp.json()
                    targets.extend(
                        PortalTarget(id=repo["full_name"], label=repo["full_name"])
                        for repo in rows
                        if repo.get("permissions", {}).get("admin")
                    )
                    if len(rows) < 100:
                        return targets
        except httpx.HTTPError as exc:
            logger.warning("github_list_repos_unreachable", extra={"error": str(exc)})
            return []
        logger.warning("github_list_repos_capped", extra={"pages": _MAX_REPO_PAGES})
        return targets

    async def register_webhook(
        self, *, access_token: str, target: str | None, webhook_url: str, secret: str
    ) -> RegisteredWebhook:
        if not target:
            raise WebhookRegistrationForbidden(
                details={"portal_key": self.portal_key, "reason": "no repository chosen"},
            )
        try:
            async with httpx.AsyncClient(base_url=_API_BASE, timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"/repos/{target}/hooks",
                    headers=_headers(access_token),
                    json={
                        "name": "web",
                        "active": True,
                        "events": _EVENTS,
                        "config": {
                            "url": webhook_url,
                            "content_type": "json",
                            "secret": secret,
                        },
                    },
                )
        except httpx.HTTPError as exc:
            # GitHub down or unreachable is a PortalError like any other refusal,
            # so the create flow degrades to manual instead of 500ing the create.
            raise PortalUnreachable(
                details={"portal_key": self.portal_key, "target": target, "error": str(exc)},
            ) from exc
        if resp.status_code != 201:
            # A missing scope (403), a repo the token cannot see (404), a rejected
            # request - all mean the account cannot register this hook, so the
            # create flow falls back to manual with the URL and secret.
            raise WebhookRegistrationForbidden(
                details={
                    "portal_key": self.portal_key,
                    "target": target,
                    "status": resp.status_code,
                },
            )
        return RegisteredWebhook(provider_webhook_id=str(resp.json()["id"]))

    async def delete_webhook(
        self, *, access_token: str, target: str | None, provider_webhook_id: str
    ) -> None:
        if not target:
            return
        async with httpx.AsyncClient(base_url=_API_BASE, timeout=_TIMEOUT) as client:
            await client.delete(
                f"/repos/{target}/hooks/{provider_webhook_id}",
                headers=_headers(access_token),
            )
