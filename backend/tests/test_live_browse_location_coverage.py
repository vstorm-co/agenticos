"""A viewer who joins a page that is not protected is not told it is."""

from unittest.mock import AsyncMock

import pytest

from app.agents.browser_events import BrowserEvent
from app.services import live_browse
from tests.test_browser_credential_publication import ProtectedStore, store_client
from tests.test_live_browse import CALL, RUN, _access, _meta, _Socket

pytestmark = pytest.mark.anyio


async def test_a_known_unprotected_location_is_not_announced_as_protected(monkeypatch) -> None:
    store = ProtectedStore()
    monkeypatch.setattr(live_browse, "_redis", store_client(store))
    monkeypatch.setattr(live_browse, "access_for", _access(control=False))
    monkeypatch.setattr(live_browse, "has_viewers", AsyncMock(return_value=True))
    await live_browse.open_view(RUN, CALL, _meta())
    await live_browse.publish(
        RUN,
        CALL,
        BrowserEvent(
            kind="browser_frame",
            call_id=CALL,
            step=0,
            image="picture",
            url="https://portal.example.test",
            title="Portal",
        ),
    )

    store.queued_messages = [
        BrowserEvent(kind="browser_step", call_id=CALL, step=1).model_dump_json()
    ]
    socket = _Socket()
    await live_browse.stream(socket, auth_token="synthetic", run_id=RUN, call_id=CALL)
    assert socket.sent[0]["frame"]["image"] == "picture"
    assert not any(sent.get("output_protected") for sent in socket.sent)
