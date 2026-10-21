"""Signing in to a site from Settings, with no agent in the browser (#2129).

The browser and Redis are replaced at the module's seams; what is real is the
hold a take-over uses, so the give-back that keeps a sign-in is the same code a
take-over runs.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.agents.browser_events import BrowserCommand, BrowserEvent
from app.agents.browser_sign_ins import SignIn
from app.agents.capabilities.browser_use._elements import Snapshot
from app.api.routes.v1.browser_sign_ins import sign_in_browser, sign_in_to_a_site
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConfigurationError,
    RateLimitError,
)
from app.core.permissions import AuthContext
from app.core.sanitize import SSRFBlockedError
from app.schemas.browser_sign_in import SignInSessionCreate
from app.services import browser_sign_in_session as session_module

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
PERSON = uuid.uuid4()
SITE = SignIn(site="notion.so", origin="https://www.notion.so", cookies=[], local_storage={})


def _ctx(user_id: uuid.UUID | None = PERSON) -> AuthContext:
    return AuthContext(user_id=user_id, organization_id=ORG, role="member")


@pytest.fixture
def deployment(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A deployment with a sign-in browser and a live view; records what was published."""
    published: list[BrowserEvent] = []
    opened: list[Any] = []
    spawned: list[Any] = []
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "http://browser:9222")
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
    monkeypatch.setattr(session_module.live_browse, "available", lambda: True)
    monkeypatch.setattr(
        session_module.live_browse,
        "open_view",
        AsyncMock(side_effect=lambda run, call, meta: opened.append((run, call, meta))),
    )
    monkeypatch.setattr(
        session_module.live_browse,
        "publish",
        AsyncMock(side_effect=lambda run, call, event: published.append(event)),
    )
    monkeypatch.setattr(session_module, "validate_webhook_url", lambda url: url)
    claimed: list[tuple[str, str]] = []
    released: list[tuple[str, str]] = []

    async def claim(key: str, holder: str, *, limit: int, hold: float) -> bool:
        assert (limit, hold) == (session_module.OPEN_LIMIT, session_module.HOLD_LIMIT + 60)
        claimed.append((key, holder))
        return len(claimed) <= limit

    async def release(key: str, holder: str) -> None:
        released.append((key, holder))

    monkeypatch.setattr(session_module.live_browse, "claim_slot", claim)
    monkeypatch.setattr(session_module.live_browse, "release_slot", release)

    def spawn(coro: Any, *, name: str) -> None:
        spawned.append(name)
        coro.close()

    monkeypatch.setattr(session_module, "spawn", spawn)
    return {
        "published": published,
        "opened": opened,
        "spawned": spawned,
        "claimed": claimed,
        "released": released,
    }


class TestWhetherItIsOffered:
    async def test_offered_with_a_browser_and_a_live_view(self, deployment: dict[str, Any]) -> None:
        assert await sign_in_browser(_ctx()) == {"available": True}

    async def test_hidden_without_a_browser_named_for_it(
        self, deployment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "")

        assert await sign_in_browser(_ctx()) == {"available": False}


class TestBeginning:
    async def test_opens_a_personal_view_held_by_the_caller(
        self, deployment: dict[str, Any]
    ) -> None:
        started = await sign_in_to_a_site(
            SignInSessionCreate(url="https://www.notion.so/login"),
            _ctx(),
            SimpleNamespace(full_name="Ada Lovelace", email="ada@example.com"),
        )

        run_id, call_id, meta = deployment["opened"][0]
        assert (started.run_id, started.call_id) == (run_id, call_id)
        assert run_id.startswith("sign-in-")
        # Only its person may see it: the pictures are them typing a password.
        assert meta.personal and meta.remembers
        assert (meta.user_id, meta.agent_id) == (str(PERSON), None)
        assert meta.task == "Sign in to www.notion.so"
        assert deployment["spawned"] == ["browser_sign_in_session"]

    async def test_an_api_key_has_no_session_to_keep(self, deployment: dict[str, Any]) -> None:
        with pytest.raises(AuthorizationError):
            await session_module.begin(_ctx(user_id=None), "https://notion.so", holder="Ada")

        assert deployment["opened"] == []

    async def test_a_key_carrying_its_issuer_has_no_session_to_keep(
        self, deployment: dict[str, Any]
    ) -> None:
        """A key's context names its issuer, so `user_id` alone let one through."""
        key = AuthContext(
            user_id=PERSON, organization_id=ORG, role="member", api_key_id=uuid.uuid4()
        )

        with pytest.raises(AuthorizationError):
            await session_module.begin(key, "https://notion.so", holder="Ada")

        assert deployment["opened"] == []

    @pytest.mark.security
    async def test_an_impersonating_administrator_keeps_no_sign_in_for_the_member(
        self, deployment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review on #2062: the administrator's own sign-in would be sealed under
        the member's name, as a chat link would be bound to them."""
        from app.services import impersonation

        monkeypatch.setattr(impersonation, "current_impersonation", lambda: uuid.uuid4())

        with pytest.raises(AuthorizationError):
            await session_module.begin(_ctx(), "https://notion.so", holder="Ada")

        assert deployment["opened"] == []

    async def test_a_person_holds_a_bounded_number_of_sign_in_browsers(
        self, deployment: dict[str, Any]
    ) -> None:
        """Each holds a page in the shared browser for up to the hold limit, watched
        or not (Codex review of #2062)."""
        for _ in range(session_module.OPEN_LIMIT):
            await session_module.begin(_ctx(), "https://notion.so", holder="Ada")

        with pytest.raises(RateLimitError):
            await session_module.begin(_ctx(), "https://notion.so", holder="Ada")

        assert len(deployment["opened"]) == session_module.OPEN_LIMIT
        assert {key for key, _ in deployment["claimed"]} == {f"browser-sign-in:{PERSON}"}

    async def test_a_deployment_without_the_browser_says_which_setting(
        self, deployment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "")

        with pytest.raises(ConfigurationError, match="BROWSER_SIGN_IN_CDP_URL"):
            await session_module.begin(_ctx(), "https://notion.so", holder="Ada")

    async def test_an_address_inside_the_network_is_refused_as_the_url_field(
        self, deployment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The browser runs on the deployment's own network; a sign-in is to a site."""

        def refuse(url: str) -> str:
            raise SSRFBlockedError("Blocked: 10.0.0.5 is a private address")

        monkeypatch.setattr(session_module, "validate_webhook_url", refuse)

        with pytest.raises(BadRequestError) as refused:
            await session_module.begin(_ctx(), "http://10.0.0.5/admin", holder="Ada")

        assert refused.value.details["fields"][0]["field"] == "url"
        assert deployment["opened"] == []


class _Page:
    def __init__(self, sign_in: SignIn | None = SITE) -> None:
        self.sign_in = sign_in
        self.clicks: list[tuple[float, float]] = []

    async def snapshot(self) -> Snapshot:
        return Snapshot(url="https://www.notion.so/login", title="Log in", elements=())

    async def screenshot(self) -> str:
        return "data:image/jpeg;base64,AA=="

    async def click_at(self, x: float, y: float) -> None:
        self.clicks.append((x, y))

    async def capture_sign_in(self) -> SignIn | None:
        return self.sign_in


class _Control:
    def __init__(self, *commands: BrowserCommand) -> None:
        self.commands = list(commands)

    async def wait(self, timeout: float) -> BrowserCommand | None:
        return self.commands.pop(0) if self.commands else None

    async def poll(self) -> BrowserCommand | None:
        return None


def _browser(page: _Page) -> Any:
    @asynccontextmanager
    async def open_page(**kwargs: Any) -> AsyncIterator[_Page]:
        yield page

    return open_page


def _give_back(by: uuid.UUID = PERSON) -> BrowserCommand:
    return BrowserCommand(type="give_back", remember=True, by="Ada", by_user_id=str(by))


class TestDriving:
    async def _drive(
        self, monkeypatch: pytest.MonkeyPatch, page: _Page, *commands: BrowserCommand
    ) -> AsyncMock:
        remember = AsyncMock()
        monkeypatch.setattr(session_module.browser_sign_in, "load_for", AsyncMock(return_value=[]))
        monkeypatch.setattr(session_module.browser_sign_in, "remember", remember)
        monkeypatch.setattr(session_module, "open_page", _browser(page))
        monkeypatch.setattr(
            session_module.live_browse, "LiveControl", MagicMock(return_value=_Control(*commands))
        )
        await session_module.drive(
            ORG, PERSON, "sign-in-1", "https://www.notion.so/login", "Ada Lovelace"
        )
        return remember

    async def test_what_the_person_does_reaches_the_page_and_their_sign_in_is_kept(
        self, deployment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        page = _Page()
        remember = await self._drive(
            monkeypatch,
            page,
            BrowserCommand(type="click", x=10, y=20, by_user_id=str(PERSON)),
            _give_back(),
        )

        assert page.clicks == [(10, 20)]
        remember.assert_awaited_once_with(ORG, PERSON, SITE)
        kinds = [event.kind for event in deployment["published"]]
        assert kinds[0] == "browser_opened" and kinds[1] == "browser_held"
        # By name, as a take-over is: the view matches it against who is watching.
        assert deployment["published"][1].by == "Ada Lovelace"
        assert deployment["published"][1].by_user_id == str(PERSON)
        released = next(e for e in deployment["published"] if e.kind == "browser_released")
        assert released.detail == "notion.so"
        assert deployment["published"][-1].outcome == "done"
        # The person's place is given back when the browser closes.
        assert deployment["released"] == [(f"browser-sign-in:{PERSON}", "sign-in-1")]

    async def test_nobody_but_the_person_drives_or_hands_it_back(
        self, deployment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Somebody else's click and give-back are dropped: the browser stays theirs
        until they hand it back themselves."""
        page = _Page()
        stranger = uuid.uuid4()
        remember = await self._drive(
            monkeypatch,
            page,
            BrowserCommand(type="click", x=1, y=1, by_user_id=str(stranger)),
            _give_back(by=stranger),
            _give_back(),
        )

        assert page.clicks == []
        remember.assert_awaited_once_with(ORG, PERSON, SITE)

    async def test_a_page_with_no_sign_in_on_it_keeps_nothing(
        self, deployment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remember = await self._drive(monkeypatch, _Page(sign_in=None), _give_back())

        remember.assert_not_awaited()

    async def test_an_unexpected_failure_keeps_its_traceback(
        self,
        deployment: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Codex on #2062: a defect raised as RuntimeError was logged as a class name
        and told the person to try again."""

        @asynccontextmanager
        async def broken(**kwargs: Any) -> AsyncIterator[_Page]:
            raise RuntimeError("a bug in the hand-over")
            yield _Page()  # pragma: no cover - never reached

        monkeypatch.setattr(session_module.browser_sign_in, "load_for", AsyncMock(return_value=[]))
        monkeypatch.setattr(session_module, "open_page", broken)
        monkeypatch.setattr(session_module.live_browse, "LiveControl", MagicMock())

        with caplog.at_level("WARNING"):
            await session_module.drive(
                ORG, PERSON, "sign-in-1", "https://www.notion.so/login", "Ada Lovelace"
            )

        [record] = [r for r in caplog.records if r.getMessage() == "browser_sign_in_unavailable"]
        assert record.exc_info is not None
        assert deployment["published"][-1].outcome == "failed"

    async def test_a_browser_that_does_not_answer_ends_the_view_with_the_reason(
        self, deployment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        @asynccontextmanager
        async def unreachable(**kwargs: Any) -> AsyncIterator[_Page]:
            raise httpx.ConnectError("refused")
            yield _Page()  # pragma: no cover - never reached

        monkeypatch.setattr(session_module.browser_sign_in, "load_for", AsyncMock(return_value=[]))
        monkeypatch.setattr(session_module, "open_page", unreachable)
        monkeypatch.setattr(session_module.live_browse, "LiveControl", MagicMock())

        await session_module.drive(
            ORG, PERSON, "sign-in-1", "https://www.notion.so/login", "Ada Lovelace"
        )

        finished = deployment["published"][-1]
        assert (finished.kind, finished.outcome) == ("browser_finished", "failed")
        assert "not answering" in (finished.detail or "")
        assert deployment["released"] == [(f"browser-sign-in:{PERSON}", "sign-in-1")]
