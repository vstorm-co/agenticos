"""Signing in with ChatGPT, and keeping the tokens it rotates in the vault."""

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from pydantic_ai.providers.openai_codex import CredentialsRefreshError, OpenAICodexCredentials

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import OpenAICodexSecret, SecretKind, seal_secret, unseal_secret
from app.core.vault import VaultScope
from app.db.models.resource_grant import Visibility
from app.services import openai_codex
from app.services.openai_codex import OpenAICodexService, VaultCodexCredentials

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _ctx(org_id=None, user_id=None) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        role=OrgRoleName.OWNER,
    )


def _pair(suffix: str = "1") -> OpenAICodexCredentials:
    return OpenAICodexCredentials(
        access_token=f"access-{suffix}",
        refresh_token=f"refresh-{suffix}",
        account_id="acct-1234abcd",
    )


def _row(org_id, pair: OpenAICodexCredentials | None = None):
    pair = pair or _pair()
    sealed = seal_secret(
        OpenAICodexSecret(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            account_id=pair.account_id,
        ),
        scope=VaultScope.organization(org_id),
    )
    row = MagicMock()
    row.id = uuid.uuid4()
    row.sealed_secret = sealed.ciphertext
    row.key_version = sealed.key_version
    return row


@asynccontextmanager
async def _session():
    yield MagicMock()


class TestTheVaultAsTheProvidersCredentialSource:
    async def test_it_loads_the_pair_the_vault_holds(self):
        org_id = uuid.uuid4()
        row = _row(org_id, _pair("current"))
        source = VaultCodexCredentials(organization_id=org_id, secret_id=row.id)

        with (
            patch.object(openai_codex, "get_db_context", _session),
            patch.object(openai_codex.organization_secret_repo, "get", AsyncMock(return_value=row)),
        ):
            loaded = await source.load()

        assert loaded == _pair("current")

    async def test_a_rotated_pair_is_sealed_over_the_old_one(self):
        """A refresh spends the refresh token, so the new pair must land under the same id."""
        org_id = uuid.uuid4()
        row = _row(org_id)
        source = VaultCodexCredentials(organization_id=org_id, secret_id=row.id)
        update = AsyncMock()

        with (
            patch.object(openai_codex, "get_db_context", _session),
            patch.object(openai_codex.organization_secret_repo, "get", AsyncMock(return_value=row)),
            patch.object(openai_codex.organization_secret_repo, "update", update),
        ):
            await source.save(_pair("rotated"))

        written = update.await_args.kwargs
        assert written["secret"] is row
        stored = unseal_secret(
            written["update_data"]["sealed_secret"],
            kind=SecretKind.OPENAI_CODEX,
            scope=VaultScope.organization(org_id),
            key_version=written["update_data"]["key_version"],
        )
        assert stored.refresh_token.get_secret_value() == "refresh-rotated"
        assert written["update_data"]["hint"] == "abcd"


class TestTakingBackWhatATaskRotated:
    """A task's `auth.json` is whatever anything it ran left there."""

    async def _swap(self, held, rotated, *, gone: bool = False):
        org_id = uuid.uuid4()
        row = None if gone else _row(org_id, held)
        source = VaultCodexCredentials(organization_id=org_id, secret_id=uuid.uuid4())
        update = AsyncMock()
        with (
            patch.object(openai_codex, "get_db_context", _session),
            patch.object(
                openai_codex.organization_secret_repo, "get_locked", AsyncMock(return_value=row)
            ),
            patch.object(openai_codex.organization_secret_repo, "update", update),
        ):
            stored = await source.swap(_pair("1"), rotated)
        return stored, update

    async def test_a_rotation_of_the_pair_written_is_kept(self):
        stored, update = await self._swap(_pair("1"), _pair("2"))
        assert stored is True
        update.assert_awaited_once()

    async def test_another_accounts_tokens_are_never_stored(self):
        """A task that ran `codex login` as somebody else, or a repository that
        planted tokens, must not turn the secret into another account."""
        other = OpenAICodexCredentials(
            access_token="a-x", refresh_token="r-x", account_id="acct-someone-else"
        )
        stored, update = await self._swap(_pair("1"), other)
        assert stored is False
        update.assert_not_awaited()

    async def test_a_sign_in_deleted_while_the_task_ran_is_not_restored(self):
        stored, update = await self._swap(_pair("1"), _pair("2"), gone=True)
        assert stored is False
        update.assert_not_awaited()

    async def test_a_newer_pair_in_the_vault_is_left_alone(self):
        """Reconnected, or refreshed by a model run, while the task ran."""
        stored, update = await self._swap(_pair("reconnected"), _pair("2"))
        assert stored is False
        update.assert_not_awaited()

    async def test_a_sign_in_deleted_from_the_vault_is_named_as_gone(self):
        source = VaultCodexCredentials(organization_id=uuid.uuid4(), secret_id=uuid.uuid4())

        with (
            patch.object(openai_codex, "get_db_context", _session),
            patch.object(
                openai_codex.organization_secret_repo, "get", AsyncMock(return_value=None)
            ),
            pytest.raises(BadRequestError, match="no longer in the vault"),
        ):
            await source.load()

    async def test_who_may_be_handed_the_sign_in_is_who_may_see_it(self):
        """Asked before the coding agent writes the tokens where Codex - and
        anything Codex runs - can read them."""
        source = VaultCodexCredentials(organization_id=uuid.uuid4(), secret_id=uuid.uuid4())
        member = MagicMock(role=OrgRoleName.MEMBER)
        resolve = AsyncMock(side_effect=[True, False])

        with (
            patch.object(openai_codex, "get_db_context", _session),
            patch.object(openai_codex.member_repo, "get", AsyncMock(return_value=member)),
            patch.object(
                openai_codex.organization_secret_repo, "get", AsyncMock(return_value=MagicMock())
            ),
            patch.object(openai_codex, "resolve_access", resolve),
        ):
            assert await source.visible_to(uuid.uuid4()) is True
            assert await source.visible_to(uuid.uuid4()) is False
        assert resolve.await_args.args[3] is openai_codex.Perm.SECRETS_VIEW

    async def test_nobody_outside_the_organization_or_after_it_is_gone(self):
        source = VaultCodexCredentials(organization_id=uuid.uuid4(), secret_id=uuid.uuid4())
        with (
            patch.object(openai_codex, "get_db_context", _session),
            patch.object(openai_codex.member_repo, "get", AsyncMock(return_value=None)),
        ):
            assert await source.visible_to(uuid.uuid4()) is False
        with (
            patch.object(openai_codex, "get_db_context", _session),
            patch.object(
                openai_codex.member_repo,
                "get",
                AsyncMock(return_value=MagicMock(role=OrgRoleName.OWNER)),
            ),
            patch.object(
                openai_codex.organization_secret_repo, "get", AsyncMock(return_value=None)
            ),
        ):
            assert await source.visible_to(uuid.uuid4()) is False

    def test_its_repr_names_the_secret_and_nothing_sealed_in_it(self):
        secret_id = uuid.uuid4()
        source = VaultCodexCredentials(organization_id=uuid.uuid4(), secret_id=secret_id)

        assert repr(source) == f"VaultCodexCredentials(secret_id={secret_id})"


def _redis() -> MagicMock:
    """A Redis that keeps what it is given, so a pending sign-in can be redeemed."""
    store: dict[str, str] = {}
    redis = MagicMock()

    async def _set(key, value, ttl=None):
        store[key] = value
        return True

    async def _getdel(key):
        return store.pop(key, None)

    redis.set = AsyncMock(side_effect=_set)
    redis.getdel = AsyncMock(side_effect=_getdel)
    redis.store = store
    return redis


def _callback(authorization_url: str, code: str = "the-code") -> str:
    state = parse_qs(urlsplit(authorization_url).query)["state"][0]
    return f"http://localhost:1455/auth/callback?code={code}&state={state}"


class TestSigningIn:
    async def test_the_verifier_stays_server_side_bound_to_whoever_started(self):
        ctx = _ctx()
        redis = _redis()

        url = await OpenAICodexService(MagicMock(), redis).start_sign_in(ctx)

        assert url.startswith("https://auth.openai.com/")
        (key, raw), ttl = next(iter(redis.store.items())), redis.set.await_args.kwargs["ttl"]
        pending = json.loads(raw)
        assert pending["user_id"] == str(ctx.subject_id)
        assert pending["organization_id"] == str(ctx.organization_id)
        assert pending["code_verifier"] not in url
        assert key.endswith(parse_qs(urlsplit(url).query)["state"][0])
        assert ttl == 15 * 60

    async def test_a_pasted_address_becomes_a_vault_secret_of_the_codex_purpose(self):
        ctx = _ctx()
        service = OpenAICodexService(MagicMock(), _redis())
        url = await service.start_sign_in(ctx)
        exchange = AsyncMock(return_value=_pair())
        create = AsyncMock(return_value="the-row")

        with (
            patch.object(openai_codex.OpenAICodexOAuthFlow, "exchange_code", exchange),
            patch.object(openai_codex.OrganizationSecretService, "create", create),
        ):
            row = await service.create(
                ctx,
                callback_url=_callback(url),
                name="Mine",
                description=None,
                visibility="private",
            )

        assert row == "the-row"
        assert exchange.await_args.args == ("the-code",)
        kwargs = create.await_args.kwargs
        assert kwargs["purpose"] == "openai_codex"
        assert kwargs["visibility"] == "private"
        assert kwargs["value"].refresh_token.get_secret_value() == "refresh-1"

    async def test_the_verifier_minted_at_the_start_is_the_one_exchanged(self):
        """PKCE only binds the code to this sign-in if the original verifier is sent."""
        ctx = _ctx()
        service = OpenAICodexService(MagicMock(), _redis())
        url = await service.start_sign_in(ctx)
        verifier = json.loads(next(iter(service.redis.store.values())))["code_verifier"]
        sent: list[str] = []

        async def _exchange(flow, code):
            sent.append(flow.code_verifier)
            return _pair()

        with (
            patch.object(openai_codex.OpenAICodexOAuthFlow, "exchange_code", _exchange),
            patch.object(openai_codex.OrganizationSecretService, "create", AsyncMock()),
        ):
            await service.create(
                ctx,
                callback_url=_callback(url),
                name="Mine",
                description=None,
                visibility="private",
            )

        assert sent == [verifier]

    async def test_reconnecting_rotates_the_existing_secret(self):
        ctx = _ctx()
        service = OpenAICodexService(MagicMock(), _redis())
        url = await service.start_sign_in(ctx)
        secret_id = uuid.uuid4()
        update = AsyncMock(return_value="the-row")

        with (
            patch.object(
                openai_codex.OpenAICodexOAuthFlow,
                "exchange_code",
                AsyncMock(return_value=_pair("new")),
            ),
            patch.object(openai_codex.OrganizationSecretService, "update", update),
        ):
            await service.reconnect(ctx, secret_id, callback_url=_callback(url))

        assert update.await_args.args[1] == secret_id
        assert update.await_args.kwargs["value"].access_token.get_secret_value() == "access-new"

    async def test_chatgpt_out_of_reach_is_a_refusal_to_start_again_not_a_500(self):
        ctx = _ctx()
        service = OpenAICodexService(MagicMock(), _redis())
        url = await service.start_sign_in(ctx)

        with (
            patch.object(
                openai_codex.OpenAICodexOAuthFlow,
                "exchange_code",
                AsyncMock(side_effect=httpx2.ConnectTimeout("timed out")),
            ),
            pytest.raises(BadRequestError) as exc,
        ):
            await service.create(
                ctx,
                callback_url=_callback(url),
                name="ChatGPT",
                description=None,
                visibility=Visibility.PRIVATE,
            )

        assert "could not be reached" in exc.value.message
        assert exc.value.details["fields"][0]["field"] == "callback_url"

    async def test_an_address_redeems_once(self):
        ctx = _ctx()
        service = OpenAICodexService(MagicMock(), _redis())
        callback = _callback(await service.start_sign_in(ctx))

        with (
            patch.object(
                openai_codex.OpenAICodexOAuthFlow, "exchange_code", AsyncMock(return_value=_pair())
            ),
            patch.object(openai_codex.OrganizationSecretService, "create", AsyncMock()),
        ):
            await service.create(
                ctx, callback_url=callback, name="Mine", description=None, visibility="private"
            )
            with pytest.raises(BadRequestError, match="expired or was already used"):
                await service.create(
                    ctx, callback_url=callback, name="Mine", description=None, visibility="private"
                )

    @pytest.mark.parametrize("who", ["another user", "another organization"])
    async def test_an_address_started_by_somebody_else_reads_as_expired(self, who):
        starter = _ctx()
        service = OpenAICodexService(MagicMock(), _redis())
        callback = _callback(await service.start_sign_in(starter))
        caller = (
            _ctx(org_id=starter.organization_id)
            if who == "another user"
            else _ctx(user_id=starter.user_id)
        )
        exchange = AsyncMock()

        with (
            patch.object(openai_codex.OpenAICodexOAuthFlow, "exchange_code", exchange),
            pytest.raises(BadRequestError, match="expired or was already used"),
        ):
            await service.reconnect(caller, uuid.uuid4(), callback_url=callback)

        exchange.assert_not_awaited()

    async def test_a_code_chatgpt_refuses_is_named_without_its_words(self):
        ctx = _ctx()
        service = OpenAICodexService(MagicMock(), _redis())
        callback = _callback(await service.start_sign_in(ctx))
        refusal = CredentialsRefreshError(
            "Token request to https://auth.openai.com failed: invalid_grant"
        )

        with (
            patch.object(
                openai_codex.OpenAICodexOAuthFlow, "exchange_code", AsyncMock(side_effect=refusal)
            ),
            pytest.raises(BadRequestError) as caught,
        ):
            await service.create(
                ctx, callback_url=callback, name="Mine", description=None, visibility="private"
            )

        assert "did not accept this sign-in" in caught.value.message
        assert "invalid_grant" not in json.dumps(caught.value.details)
        assert caught.value.details["fields"][0]["field"] == "callback_url"


class TestReadingThePastedAddress:
    def test_a_bare_query_string_is_read_too(self):
        assert openai_codex._read_callback("  ?code=c&state=s ") == ("c", "s")

    def test_a_refusal_from_chatgpt_is_named_as_one(self):
        with pytest.raises(BadRequestError, match="refused"):
            openai_codex._read_callback(
                "http://localhost:1455/auth/callback?error=access_denied&state=s"
            )

    @pytest.mark.parametrize(
        "pasted",
        [
            "http://localhost:1455/auth/callback?state=s",
            "http://localhost:1455/auth/callback?code=c",
            "not a url",
        ],
    )
    def test_an_address_without_a_code_and_a_state_is_refused(self, pasted):
        with pytest.raises(BadRequestError, match="Paste the whole address"):
            openai_codex._read_callback(pasted)
