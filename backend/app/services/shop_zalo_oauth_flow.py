"""Start / callback for Shop Zalo OA OAuth on Agentra (D3 B65)."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.vault import VaultScope, seal, unseal
from app.db.models.channel_bot import (
    AUTH_METHOD_OAUTH,
    BOT_KIND_SHOP_CSKH,
    ChannelBot,
)
from app.repositories import channel_bot_repo, shop_channel_bot as shop_bot_repo
from app.services.channel_bot import unseal_bot_token
from app.services.shop_zalo_oauth_client import ShopZaloOAuthClient
from app.services.shop_zalo_oauth_crypto import (
    sign_shop_zalo_oauth_state,
    verify_shop_zalo_oauth_state,
)
from app.services.shop_zalo_oauth_pkce import generate_pkce_pair

logger = logging.getLogger(__name__)


def _redirect(base: str | None, *, fallback: str, **params: str) -> str:
    target = (base or fallback).strip() or fallback
    if not params:
        return target
    sep = "&" if "?" in target else "?"
    return f"{target}{sep}{urlencode(params)}"


def _fail(failure_url: str | None, reason: str, **extra: Any) -> str:
    logger.warning("zalo oauth callback failed: %s %s", reason, extra)
    return _redirect(
        failure_url,
        fallback=settings.SHOP_AI_ZALO_OAUTH_FAILURE_REDIRECT,
        zalo_oauth="error",
        reason=reason[:120],
    )


def _seal_credential(plain: str, *, organization_id: UUID, key_version: int) -> str:
    return seal(
        plain,
        scope=VaultScope.organization(organization_id),
        key_version=key_version,
    ).ciphertext


async def start_shop_zalo_oauth(
    db: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    name: str,
    default_kb_id: UUID | None = None,
    bot_id: UUID | None = None,
    return_url: str | None = None,
    failure_url: str | None = None,
) -> dict[str, str]:
    clean_name = (name or "").strip()
    if not clean_name and bot_id is None:
        raise BadRequestError(message="name is required for new Zalo OAuth connect")
    if bot_id is not None:
        existing = await shop_bot_repo.get_for_shop(
            db,
            bot_id=bot_id,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
        )
        if existing is None:
            raise NotFoundError(
                message="Channel bot not found",
                details={"bot_id": str(bot_id), "tenant_id": str(minerp_tenant_id)},
            )
    verifier, challenge = generate_pkce_pair()
    ok_redirect = return_url or settings.SHOP_AI_ZALO_OAUTH_SUCCESS_REDIRECT
    fail_redirect = failure_url or settings.SHOP_AI_ZALO_OAUTH_FAILURE_REDIRECT
    state = sign_shop_zalo_oauth_state(
        {
            "organization_id": str(organization_id),
            "minerp_tenant_id": str(minerp_tenant_id),
            "name": clean_name,
            "default_kb_id": str(default_kb_id) if default_kb_id else "",
            "bot_id": str(bot_id) if bot_id else "",
            "code_verifier": verifier,
            "return_url": ok_redirect,
            "failure_url": fail_redirect,
            "nonce": secrets.token_hex(8),
        }
    )
    url = ShopZaloOAuthClient().authorize_url(state=state, code_challenge=challenge)
    return {"authorize_url": url}


async def handle_shop_zalo_oauth_callback(
    db: AsyncSession,
    *,
    code: str | None,
    state: str | None,
    oa_id: str | None = None,
) -> str:
    if not code or not state:
        return _fail(None, "missing_code_or_state")
    try:
        payload = verify_shop_zalo_oauth_state(state)
    except BadRequestError as exc:
        return _fail(None, exc.message)
    failure_url = str(payload.get("failure_url") or "")
    return_url = str(payload.get("return_url") or "")
    try:
        organization_id = UUID(str(payload.get("organization_id")))
        minerp_tenant_id = UUID(str(payload.get("minerp_tenant_id")))
        verifier = str(payload.get("code_verifier") or "")
        if not verifier:
            raise BadRequestError(message="OAuth state missing code_verifier")
        tokens = await ShopZaloOAuthClient().exchange_code(code=code, code_verifier=verifier)
        bot = await _upsert_oauth_bot(
            db,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            name=str(payload.get("name") or "Shop Zalo").strip() or "Shop Zalo",
            default_kb_id=_optional_uuid(payload.get("default_kb_id")),
            bot_id=_optional_uuid(payload.get("bot_id")),
            oa_id=(oa_id or "").strip() or None,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_in=int(tokens["expires_in"]),
        )
        return _redirect(
            return_url,
            fallback=settings.SHOP_AI_ZALO_OAUTH_SUCCESS_REDIRECT,
            zalo_oauth="success",
            bot_id=str(bot.id),
        )
    except (BadRequestError, NotFoundError) as exc:
        return _fail(failure_url, exc.message)
    except Exception as exc:
        logger.exception("zalo oauth callback unexpected error")
        return _fail(failure_url, str(exc)[:120])


def _optional_uuid(raw: Any) -> UUID | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return UUID(text)


async def _upsert_oauth_bot(
    db: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    name: str,
    default_kb_id: UUID | None,
    bot_id: UUID | None,
    oa_id: str | None,
    access_token: str,
    refresh_token: str,
    expires_in: int,
) -> ChannelBot:
    expires_at = datetime.now(UTC) + timedelta(seconds=max(expires_in - 300, 60))
    sealed_access = seal(access_token, scope=VaultScope.organization(organization_id))
    kv = sealed_access.key_version
    refresh_enc = _seal_credential(refresh_token, organization_id=organization_id, key_version=kv)
    update_data = {
        "name": name,
        "token_encrypted": sealed_access.ciphertext,
        "secret_key_version": kv,
        "refresh_token_encrypted": refresh_enc,
        "token_expires_at": expires_at,
        "auth_method": AUTH_METHOD_OAUTH,
        "webhook_mode": True,
        "default_kb_id": default_kb_id,
        "zalo_oa_id": oa_id,
        "is_active": True,
        "minerp_tenant_id": minerp_tenant_id,
        "bot_kind": BOT_KIND_SHOP_CSKH,
    }
    if bot_id:
        bot = await shop_bot_repo.get_for_shop(
            db,
            bot_id=bot_id,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
        )
        if bot is None:
            raise NotFoundError(
                message="Channel bot not found",
                details={"bot_id": str(bot_id), "tenant_id": str(minerp_tenant_id)},
            )
        return await channel_bot_repo.update(db, db_bot=bot, update_data=update_data)

    webhook_plain = secrets.token_urlsafe(32)
    webhook_enc = _seal_credential(webhook_plain, organization_id=organization_id, key_version=kv)
    return await channel_bot_repo.create(
        db,
        organization_id=organization_id,
        platform="zalo",
        name=name,
        token_encrypted=sealed_access.ciphertext,
        secret_key_version=kv,
        webhook_mode=True,
        webhook_secret_encrypted=webhook_enc,
        minerp_tenant_id=minerp_tenant_id,
        bot_kind=BOT_KIND_SHOP_CSKH,
        default_kb_id=default_kb_id,
        auth_method=AUTH_METHOD_OAUTH,
        refresh_token_encrypted=refresh_enc,
        token_expires_at=expires_at,
        zalo_oa_id=oa_id,
    )


async def ensure_shop_zalo_access_token(db: AsyncSession, bot: ChannelBot) -> str:
    if bot.platform != "zalo" or bot.auth_method != AUTH_METHOD_OAUTH:
        return unseal_bot_token(bot)
    now = datetime.now(UTC)
    expires = bot.token_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires and expires > now + timedelta(minutes=5):
        return unseal_bot_token(bot)
    if not bot.refresh_token_encrypted:
        raise BadRequestError(message="Missing Zalo refresh token")
    refresh_plain = unseal(
        bot.refresh_token_encrypted,
        scope=VaultScope.organization(bot.organization_id),
        key_version=bot.secret_key_version,
    )
    tokens = await ShopZaloOAuthClient().refresh_access_token(refresh_token=refresh_plain)
    expires_at = datetime.now(UTC) + timedelta(seconds=max(int(tokens["expires_in"]) - 300, 60))
    sealed_access = seal(
        tokens["access_token"],
        scope=VaultScope.organization(bot.organization_id),
        key_version=bot.secret_key_version,
    )
    refresh_enc = _seal_credential(
        tokens["refresh_token"],
        organization_id=bot.organization_id,
        key_version=bot.secret_key_version,
    )
    updated = await channel_bot_repo.update(
        db,
        db_bot=bot,
        update_data={
            "token_encrypted": sealed_access.ciphertext,
            "refresh_token_encrypted": refresh_enc,
            "token_expires_at": expires_at,
        },
    )
    return unseal_bot_token(updated)


async def refresh_shop_zalo_oauth_bot(db: AsyncSession, bot: ChannelBot) -> ChannelBot:
    """Proactive refresh (Prefect beat B76) — same as on-demand ensure."""
    await ensure_shop_zalo_access_token(db, bot)
    refreshed = await channel_bot_repo.get_for_inbound(db, bot.id)
    if refreshed is None:
        return bot
    return refreshed


async def refresh_expiring_shop_zalo_oauth_tokens(db: AsyncSession) -> dict[str, int]:
    from app.repositories import channel_bot_repo

    ok = 0
    failed = 0
    bots = await channel_bot_repo.list_zalo_oauth_expiring(db, within_hours=2)
    for bot in bots:
        try:
            await refresh_shop_zalo_oauth_bot(db, bot)
            ok += 1
        except Exception:
            failed += 1
            logger.exception("Shop Zalo OAuth refresh failed bot=%s", bot.id)
    return {"refreshed": ok, "failed": failed}
