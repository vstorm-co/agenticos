"""Tests for embedded agents — an agent published to the public internet.

Everything here is about admission. A widget key lives in a `<script>` tag on
somebody's marketing site, so the key is not a secret and cannot be the whole
authorization; what actually protects the deployment is the origin allow-list,
the token check in `jwt` mode, and the per-visitor rate limit.

The refusals are tested as hard as the successes, because every one of them
fails open if it regresses: an empty allow-list that admits everybody, a `jwt`
embed that accepts an unsigned token, a rate limit that resets per socket.
"""

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest

from app.core.exceptions import BadRequestError
from app.services.agent_embed import AgentEmbedService, EmbedDenied, _origin_of
from app.services.embed_session import _allowed, _buckets

MODULE = "app.services.agent_embed"


def _embed(**overrides):
    embed = MagicMock()
    embed.id = uuid.uuid4()
    embed.organization_id = uuid.uuid4()
    embed.agent_id = uuid.uuid4()
    embed.owner_user_id = uuid.uuid4()
    embed.name = "Support"
    embed.public_key = "key-123"
    embed.auth_mode = "public"
    embed.jwt_secret_encrypted = None
    embed.allowed_origins = ["https://acme.test"]
    embed.theme = {}
    embed.context = None
    embed.is_active = True
    embed.rate_limit_per_minute = 10
    for key, value in overrides.items():
        setattr(embed, key, value)
    return embed


def _service(embed=None) -> AgentEmbedService:
    service = AgentEmbedService(MagicMock())
    return service


class TestOriginIsThePerimeter:
    @pytest.mark.anyio
    async def test_a_listed_origin_is_admitted(self):
        with patch(f"{MODULE}.agent_embed_repo.get_by_key", new=AsyncMock(return_value=_embed())):
            embed, visitor = await _service().admit(
                "key-123", origin="https://acme.test", token=None
            )

        assert visitor is None
        assert embed.public_key == "key-123"

    @pytest.mark.anyio
    async def test_an_unlisted_origin_is_refused(self):
        with (
            patch(f"{MODULE}.agent_embed_repo.get_by_key", new=AsyncMock(return_value=_embed())),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit("key-123", origin="https://evil.test", token=None)

    @pytest.mark.anyio
    async def test_an_empty_allow_list_admits_nobody(self):
        """The safe default, and the only honest one: the key is public, so
        without an origin the key alone would be the entire authorization."""
        with (
            patch(
                f"{MODULE}.agent_embed_repo.get_by_key",
                new=AsyncMock(return_value=_embed(allowed_origins=[])),
            ),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit("key-123", origin="https://acme.test", token=None)

    @pytest.mark.anyio
    async def test_a_request_with_no_origin_at_all_is_refused(self):
        """curl sends none. A browser on an allowed page always does."""
        with (
            patch(f"{MODULE}.agent_embed_repo.get_by_key", new=AsyncMock(return_value=_embed())),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit("key-123", origin=None, token=None)

    @pytest.mark.anyio
    async def test_a_paused_widget_stops_answering_immediately(self):
        with (
            patch(
                f"{MODULE}.agent_embed_repo.get_by_key",
                new=AsyncMock(return_value=_embed(is_active=False)),
            ),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit("key-123", origin="https://acme.test", token=None)

    def test_a_path_and_trailing_slash_do_not_change_the_origin(self):
        """Somebody will paste a full page URL into the allow-list."""
        assert _origin_of("https://acme.test/pricing/") == "https://acme.test"
        assert _origin_of("HTTPS://ACME.TEST") == "https://acme.test"

    def test_a_different_port_is_a_different_origin(self):
        """The browser treats it as one, so the allow-list has to."""
        assert _origin_of("http://localhost:3000") != _origin_of("http://localhost:8000")


class TestTokenMode:
    def _jwt_embed(self, secret: str = "s" * 32):
        return _embed(auth_mode="jwt", jwt_secret_encrypted="sealed")

    @pytest.mark.anyio
    async def test_a_valid_token_identifies_the_visitor(self):
        secret = "s" * 32
        token = jwt.encode({"sub": "user-42", "iat": int(time.time())}, secret, algorithm="HS256")
        with (
            patch(
                f"{MODULE}.agent_embed_repo.get_by_key",
                new=AsyncMock(return_value=self._jwt_embed()),
            ),
            patch(f"{MODULE}.unseal", return_value=secret),
        ):
            _embed_row, visitor = await _service().admit(
                "key-123", origin="https://acme.test", token=token
            )

        assert visitor == "user-42"

    @pytest.mark.anyio
    async def test_a_token_signed_with_the_wrong_secret_is_refused(self):
        token = jwt.encode({"sub": "user-42"}, "attacker-secret", algorithm="HS256")
        with (
            patch(
                f"{MODULE}.agent_embed_repo.get_by_key",
                new=AsyncMock(return_value=self._jwt_embed()),
            ),
            patch(f"{MODULE}.unseal", return_value="s" * 32),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit("key-123", origin="https://acme.test", token=token)

    @pytest.mark.anyio
    async def test_a_missing_token_is_refused_rather_than_treated_as_anonymous(self):
        """The failure that matters: `jwt` mode silently degrading to `public`."""
        with (
            patch(
                f"{MODULE}.agent_embed_repo.get_by_key",
                new=AsyncMock(return_value=self._jwt_embed()),
            ),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit("key-123", origin="https://acme.test", token=None)

    @pytest.mark.anyio
    async def test_a_token_with_no_subject_is_refused(self):
        """Without one there is nothing to rate-limit per visitor, and a single
        leaked token becomes the whole widget's budget."""
        secret = "s" * 32
        token = jwt.encode({"iat": int(time.time())}, secret, algorithm="HS256")
        with (
            patch(
                f"{MODULE}.agent_embed_repo.get_by_key",
                new=AsyncMock(return_value=self._jwt_embed()),
            ),
            patch(f"{MODULE}.unseal", return_value=secret),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit("key-123", origin="https://acme.test", token=token)

    @pytest.mark.anyio
    async def test_a_stale_token_is_refused(self):
        """One that leaked out of a browser months ago must not still work."""
        secret = "s" * 32
        old = int(time.time()) - 60 * 60 * 24 * 30
        token = jwt.encode({"sub": "u", "iat": old}, secret, algorithm="HS256")
        with (
            patch(
                f"{MODULE}.agent_embed_repo.get_by_key",
                new=AsyncMock(return_value=self._jwt_embed()),
            ),
            patch(f"{MODULE}.unseal", return_value=secret),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit("key-123", origin="https://acme.test", token=token)

    @pytest.mark.anyio
    async def test_the_origin_is_checked_before_the_token(self):
        """A probe from an unlisted site must learn nothing about tokens — the
        unseal is what would tell it, so it must never happen."""
        unseal = MagicMock()
        with (
            patch(
                f"{MODULE}.agent_embed_repo.get_by_key",
                new=AsyncMock(return_value=self._jwt_embed()),
            ),
            patch(f"{MODULE}.unseal", unseal),
            pytest.raises(EmbedDenied),
        ):
            await _service().admit("key-123", origin="https://evil.test", token="anything")

        unseal.assert_not_called()


class TestSecretRules:
    def test_a_token_embed_must_bring_a_secret(self):
        with pytest.raises(BadRequestError):
            _service()._check_secret("jwt", None)

    def test_a_public_embed_refuses_a_secret_nothing_would_read(self):
        """Stored and never consulted is a secret somebody believes protects them."""
        with pytest.raises(BadRequestError):
            _service()._check_secret("public", "s" * 32)


class TestRateLimit:
    def test_a_visitor_is_cut_off_after_their_allowance(self):
        _buckets.clear()
        key = (str(uuid.uuid4()), "visitor-1")

        assert all(_allowed(key, 3) for _ in range(3))
        assert _allowed(key, 3) is False

    def test_two_visitors_do_not_share_an_allowance(self):
        _buckets.clear()
        widget = str(uuid.uuid4())

        assert _allowed((widget, "a"), 1) is True
        assert _allowed((widget, "b"), 1) is True
        assert _allowed((widget, "a"), 1) is False
