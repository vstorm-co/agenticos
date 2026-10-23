"""Signing in to a site from Settings, with no agent in the browser (#2129).

The other way a sign-in is kept is a take-over: an agent's browse meets a login
page, its person takes the browser and hands it back with *keep me signed in*.
This is the same hold and the same give-back, started by the person on a site of
their choosing, on the browser the deployment names in
`BROWSER_SIGN_IN_CDP_URL`.

The browse is published to the live view like any other, at its own address, so
the console's browse page is the screen it is done on. It is **personal**: only
the person who started it may watch it, because its pictures are them typing a
password.
"""

import logging
from datetime import UTC, datetime
from typing import NamedTuple
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from app.agents.browser_events import BrowserCommand, BrowserEvent
from app.agents.capabilities.browser_use import WebBrowserConfig, validate_cdp_url
from app.agents.capabilities.browser_use._endpoint import EndpointError
from app.agents.capabilities.browser_use._loop import (
    HOLD_LIMIT,
    BrowseSession,
    PageSession,
    hand_over,
)
from app.agents.capabilities.browser_use._page import PagePolicy, open_page
from app.core.background import spawn
from app.core.config import settings
from app.core.exceptions import AuthorizationError, ConfigurationError, RateLimitError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.core.sanitize import SSRFBlockedError, UrlRefusedError, validate_webhook_url
from app.services import browser_sign_in, live_browse
from app.services.impersonation import refuse_binding_while_impersonating

logger = logging.getLogger(__name__)

CALL_ID = "sign-in"
"""The one browse a sign-in session holds, as the live view keys it."""

OPEN_LIMIT = 3
"""How many sign-in browsers one person may hold open at once.

Each holds a page in the shared browser for up to `HOLD_LIMIT` whether or not
anybody is watching it, so an unbounded number is one account exhausting the
browser and the API process for everybody. Three covers signing in to a couple
of sites side by side, and a tab closed without finishing frees its place when
it lapses.
"""


def _slots(user_id: UUID) -> str:
    return f"browser-sign-in:{user_id}"


_POLICY = PagePolicy(allowed_domains=None, candidate_cap=60, preview_width=1024)
"""Where the person may go: anywhere their own sign-in leads. Single sign-on sends
them through another domain, and they are the one driving."""


class SignInSession(NamedTuple):
    """Where the browse is watched: the live view's run and call."""

    run_id: str
    call_id: str


def available() -> bool:
    """Whether this deployment can open a browser for signing in from Settings."""
    return bool(settings.BROWSER_SIGN_IN_CDP_URL) and live_browse.available()


async def begin(ctx: AuthContext, url: str, *, holder: str) -> SignInSession:
    """Open a browser on `url` for the caller to sign in, and say where to watch it.

    `holder` is the caller's name as the live view shows who has the browser - the
    same name a take-over is stamped with, which is how the view knows the person
    watching is the one holding it.

    Raises:
        AuthorizationError: The caller is an API key, which has no session to keep.
        ConfigurationError: The deployment names no browser for this, or has no
            live view to show it in.
        RateLimitError: The caller already holds `OPEN_LIMIT` sign-in browsers.
        BadRequestError: `url` is not a public http(s) address - the browser runs
            on the deployment's own network, and a sign-in is to somebody's site.
    """
    user_id = ctx.user_id
    # A key's context carries its issuer's id, so the key is asked about directly.
    if user_id is None or ctx.api_key_id is not None:
        raise AuthorizationError(
            message="Signing in to a site keeps a person's session; an API key has none.",
            details={"subject": "api_key"},
        )
    # Kept under the account being acted as: an administrator impersonating a member
    # would seal their own sign-in under the member's name.
    refuse_binding_while_impersonating("Keeping a browser sign-in")
    if not available():
        raise ConfigurationError(
            message=(
                "This deployment has no browser to sign in with: set "
                "BROWSER_SIGN_IN_CDP_URL to its browser service."
            ),
            details={"setting": "BROWSER_SIGN_IN_CDP_URL"},
        )
    try:
        validate_webhook_url(url)
    except (SSRFBlockedError, UrlRefusedError) as exc:
        raise refused_field("url", str(exc)) from exc
    run_id = f"sign-in-{uuid4().hex}"
    site = urlsplit(url).hostname or url
    if not await live_browse.claim_slot(
        _slots(user_id), run_id, limit=OPEN_LIMIT, hold=HOLD_LIMIT + 60
    ):
        raise RateLimitError(
            message=(
                f"You already have {OPEN_LIMIT} sign-in browsers open. "
                "Finish or close one, then try again."
            ),
            details={"limit": OPEN_LIMIT},
        )
    await live_browse.open_view(
        run_id,
        CALL_ID,
        live_browse.BrowseMeta(
            organization_id=ctx.organization_id,
            agent_id=None,
            user_id=str(user_id),
            remembers=True,
            personal=True,
            task=f"Sign in to {site}",
            started_at=datetime.now(UTC),
        ),
    )
    spawn(
        drive(ctx.organization_id, user_id, run_id, url, holder),
        name="browser_sign_in_session",
    )
    return SignInSession(run_id=run_id, call_id=CALL_ID)


async def drive(organization_id: UUID, user_id: UUID, run_id: str, url: str, holder: str) -> None:
    """Hold the browser for its person until they give it back, keeping what they ask.

    Starts from the sign-ins they already kept, so signing in again to a site
    replaces a stale session rather than adding a second one. A browser that does
    not answer ends the view with the reason instead of leaving it waiting.
    """
    control = live_browse.LiveControl(run_id, CALL_ID)

    async def emit(event: BrowserEvent) -> bool:
        await live_browse.publish(run_id, CALL_ID, event)
        return True

    # Only the person's own give-back reaches this: `hand_over` drops every
    # command from anybody but the holder it was given.
    async def keep(page: PageSession, command: BrowserCommand) -> str | None:
        sign_in = await page.capture_sign_in()
        if sign_in is None:
            return None
        await browser_sign_in.remember(organization_id, user_id, sign_in)
        return sign_in.site

    try:
        cdp_url = settings.BROWSER_SIGN_IN_CDP_URL
        try:
            validate_cdp_url(WebBrowserConfig(cdp_url=cdp_url))
            sign_ins = await browser_sign_in.load_for(organization_id, user_id)
            async with open_page(
                cdp_url=cdp_url, start_url=url, policy=_POLICY, sign_ins=sign_ins
            ) as page:
                snapshot = await page.snapshot()
                await emit(
                    BrowserEvent(
                        kind="browser_opened",
                        call_id=CALL_ID,
                        step=0,
                        url=snapshot.url,
                        title=snapshot.title,
                        run_id=run_id,
                    )
                )
                await hand_over(
                    BrowseSession(page=page),
                    control,
                    emit,
                    call_id=CALL_ID,
                    by=holder,
                    by_user_id=str(user_id),
                    remember=keep,
                )
                await emit(
                    BrowserEvent(kind="browser_finished", call_id=CALL_ID, step=0, outcome="done")
                )
        except (httpx.HTTPError, OSError, EndpointError, UrlRefusedError, RuntimeError) as exc:
            # The host only: an endpoint URL can carry a token. A plain
            # RuntimeError is also what the CDP client raises for a page that went
            # away, but it can be a defect here too, so it keeps its traceback.
            logger.warning(
                "browser_sign_in_unavailable",
                extra={"host": urlsplit(cdp_url).hostname, "error": type(exc).__name__},
                exc_info=type(exc) is RuntimeError,
            )
            await emit(
                BrowserEvent(
                    kind="browser_finished",
                    call_id=CALL_ID,
                    step=0,
                    outcome="failed",
                    detail="The browser is not answering right now. Try again in a minute.",
                )
            )
    finally:
        await live_browse.release_slot(_slots(user_id), run_id)
