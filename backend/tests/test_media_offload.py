"""Offloading a compacted history's media, and the ways it must not go wrong.

The `media` capability rewrites what is *stored*, so every property worth a test
is about a conversation days later rather than about the run it happened in
(#55):

- the bytes leave the history and the history still means the same thing;
- one tenant's content hash does not resolve inside another's store;
- restoring does not depend on the capability still being bound, because the
  markers outlive the binding;
- neither direction loses the history when the store fails, because the summary
  a model was paid to produce is worth more than the space it takes.
"""

from __future__ import annotations

import base64
from typing import Any
from uuid import uuid4

import pytest
from pydantic_ai_harness.media import media_uri_for

from app.agents.capabilities.media import (
    MediaConfig,
    MediaOffload,
    OrganizationMediaStore,
    restore_stored_media,
)
from app.agents.capabilities.media._capability import restore_media
from app.services.file_storage import LocalFileStorage

pytestmark = pytest.mark.anyio

PICTURE = b"\x89PNG\r\n\x1a\n" + b"pixels" * 20_000


def _history(data: bytes) -> list[dict[str, Any]]:
    """A compacted history with one picture in it, in the shape the library dumps."""
    return [
        {
            "kind": "request",
            "parts": [
                {
                    "part_kind": "user-prompt",
                    "content": [
                        "Here is the chart.",
                        {
                            "kind": "binary",
                            "data": base64.b64encode(data).decode(),
                            "media_type": "image/png",
                        },
                    ],
                }
            ],
        }
    ]


def _offload(storage: LocalFileStorage, organization_id: Any) -> MediaOffload[object]:
    capability: MediaOffload[object] = MediaOffload(
        organization_id=organization_id, threshold_bytes=1_024
    )
    capability._store = OrganizationMediaStore(organization_id, storage)
    return capability


class TestWhatLeavesTheHistory:
    async def test_a_large_picture_is_replaced_by_a_reference(self, tmp_path: Any) -> None:
        storage = LocalFileStorage(base_dir=tmp_path)
        organization_id = uuid4()

        stored = await _offload(storage, organization_id).externalize(_history(PICTURE))

        blob = str(stored)
        assert base64.b64encode(PICTURE).decode() not in blob
        assert media_uri_for(PICTURE) in blob

    async def test_the_bytes_come_back_exactly(self, tmp_path: Any) -> None:
        """The whole bargain: smaller in storage, identical to the model."""
        storage = LocalFileStorage(base_dir=tmp_path)
        organization_id = uuid4()
        original = _history(PICTURE)

        stored = await _offload(storage, organization_id).externalize(original)
        restored = await restore_media(
            stored, media_store=OrganizationMediaStore(organization_id, storage)
        )

        assert restored == original

    async def test_something_small_is_left_where_it_is(self, tmp_path: Any) -> None:
        """A marker is about 120 bytes and costs a store round trip on both
        sides, so offloading a thumbnail makes the history bigger and slower."""
        storage = LocalFileStorage(base_dir=tmp_path)
        original = _history(b"tiny")

        stored = await _offload(storage, uuid4()).externalize(original)

        assert stored == original

    async def test_the_same_picture_twice_is_stored_once(self, tmp_path: Any) -> None:
        """Content-addressed: the path is the digest, so a second write of the
        same bytes is a transfer paid for nothing."""
        storage = LocalFileStorage(base_dir=tmp_path)
        organization_id = uuid4()
        offload = _offload(storage, organization_id)

        await offload.externalize(_history(PICTURE))
        await offload.externalize(_history(PICTURE))

        written = list((tmp_path / "media" / str(organization_id)).iterdir())
        assert len(written) == 1


class TestTenantIsolation:
    @pytest.mark.security
    async def test_one_organizations_digest_does_not_resolve_in_another(
        self, tmp_path: Any
    ) -> None:
        """A media URI is a content hash, so two tenants holding the same picture
        compute the same URI. The organization is part of the path and comes from
        the run, so presenting a hash reaches nothing across the boundary."""
        storage = LocalFileStorage(base_dir=tmp_path)
        theirs = uuid4()
        await _offload(storage, theirs).externalize(_history(PICTURE))

        mine = OrganizationMediaStore(uuid4(), storage)

        assert not await mine.exists(media_uri_for(PICTURE))
        with pytest.raises(FileNotFoundError):
            await mine.get(media_uri_for(PICTURE))

    @pytest.mark.security
    async def test_the_store_offers_no_public_url(self, tmp_path: Any) -> None:
        """A URL a model provider can fetch is a URL anybody can, and these bytes
        are a tenant's."""
        store = OrganizationMediaStore(uuid4(), LocalFileStorage(base_dir=tmp_path))

        assert await store.public_url(media_uri_for(PICTURE)) is None

    async def test_a_uri_that_is_not_one_is_not_found_rather_than_an_error(
        self, tmp_path: Any
    ) -> None:
        store = OrganizationMediaStore(uuid4(), LocalFileStorage(base_dir=tmp_path))

        assert not await store.exists("not-a-media-uri")


class TestRestoringDoesNotDependOnTheBinding:
    async def test_a_history_with_markers_is_restored_with_no_capability_in_sight(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An agent can be unbound, or the next turn can run a different agent.
        The markers outlive the binding, and a marker nobody re-inlines is a
        picture the model is handed in a language it does not read."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
        organization_id = uuid4()
        stored = await _offload(LocalFileStorage(base_dir=tmp_path), organization_id).externalize(
            _history(PICTURE)
        )

        restored = await restore_stored_media(stored, organization_id=organization_id)

        assert restored == _history(PICTURE)

    async def test_a_history_with_nothing_to_restore_is_returned_unchanged(self) -> None:
        plain = _history(b"tiny")

        assert await restore_stored_media(plain, organization_id=uuid4()) == plain

    async def test_an_empty_history_needs_no_store_at_all(self) -> None:
        assert await restore_stored_media([], organization_id=uuid4()) == []


class TestFailingSoft:
    async def test_a_store_that_cannot_write_keeps_the_history(
        self, tmp_path: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The alternative to a smaller history is the history. Losing the
        summary a model was paid to produce is the worse outcome."""
        storage = LocalFileStorage(base_dir=tmp_path)
        offload = _offload(storage, uuid4())

        async def _refuse(*_args: object, **_kwargs: object) -> None:
            raise OSError("no space left on device")

        offload._store.put = _refuse  # type: ignore[union-attr, method-assign]
        original = _history(PICTURE)

        assert await offload.externalize(original) == original
        assert "media_externalize_failed" in caplog.text

    async def test_a_store_that_cannot_read_keeps_the_history(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The markers then reach the model as the dicts they are, which is a
        worse answer and still an answer."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
        stored = await _offload(LocalFileStorage(base_dir=tmp_path), uuid4()).externalize(
            _history(PICTURE)
        )

        # A different organization, so every referenced digest is missing.
        restored = await restore_stored_media(stored, organization_id=uuid4())

        assert restored == stored
        assert "media_restore_failed" in caplog.text


class TestWhatAnUnconfiguredCapabilityContributes:
    async def test_outside_a_run_it_offloads_nothing(self) -> None:
        """A preview builds capabilities with no organization. Offloading
        somewhere shared would be worse than not offloading."""
        capability: MediaOffload[object] = MediaOffload(organization_id=None)
        original = _history(PICTURE)

        assert await capability.externalize(original) == original
        assert capability.store() is None

    def test_the_default_threshold_is_the_schema_s(self) -> None:
        assert MediaOffload[object]().threshold_bytes == MediaConfig().threshold_bytes

    def test_inside_a_run_the_store_is_built_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A store opens a backend and is asked for on every offload; building
        one per call would repeat that for no reader's benefit."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "MEDIA_DIR", "media")
        capability: MediaOffload[object] = MediaOffload(organization_id=uuid4())

        first = capability.store()

        assert first is not None
        assert capability.store() is first

    async def test_the_store_answers_no_metadata(self, tmp_path: Any) -> None:
        """Nothing is stored beside the bytes. The method exists because the
        protocol has it, and answering `{}` is the honest shape of "nothing"."""
        store = OrganizationMediaStore(uuid4(), LocalFileStorage(base_dir=tmp_path))

        assert await store.get_metadata(media_uri_for(PICTURE)) == {}
