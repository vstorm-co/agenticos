"""Saved protected state stays private through admission, row races and restore rollback."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.audience import RunAudience
from app.agents.deps import AgentDeps
from app.core.browser_continuation import BrowserContinuationReason, BrowserContinuationRefused
from app.core.browser_session import MAX_SESSION_BYTES, ProtectedSignIn
from app.core.secret_scopes import browser_sign_in_scope
from app.core.vault import seal
from app.db.models.agent_run import AgentRun
from app.db.models.browser_sign_in import BrowserSignIn
from app.db.models.organization import OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.services.browser_credentials import _saved_sessions as saved_sessions
from tests.integration.test_browser_credential_continuations import continuation as continuation
from tests.integration.test_browser_credential_plans import browser as browser
from tests.test_browser_credential_native import ORIGIN
from tests.test_browser_session import PRIVATE

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def admitted_deps(b):
    return AgentDeps(
        organization_id=b.org.id,
        user_id=str(b.owner.id),
        agent_id=b.agent.id,
        run_id=b.run.id,
        run_person=b.owner.id,
        audience=RunAudience(user_id=b.owner.id, browses_signed_in=True),
    )


def sealed_payload(b, value):
    return seal(
        json.dumps(value),
        scope=browser_sign_in_scope(
            organization_id=b.org.id,
            user_id=b.owner.id,
            protection_kind="credential",
        ),
    )


async def replace_payload(b, row, value):
    sealed = sealed_payload(b, value)
    row.sealed_state = sealed.ciphertext
    row.secret_key_version = sealed.key_version
    await b.db.flush()


@pytest.fixture
async def saved(continuation):
    f, b = continuation, continuation.browser
    claim = await f.claimed(keep=True)
    state = f.state(claim)
    await f.service.finish(b.ctx, b.identity, claim, state)
    receipt = await f.service.get(b.ctx, b.run.id, f.submission_id)
    row = await b.db.get(BrowserSignIn, receipt.saved_sign_in_id)
    assert row is not None and row.protection_kind == "credential"
    assert row.last_used_at is None and PRIVATE not in row.sealed_state
    return b, state, row


@pytest.fixture
def restore_transactions(engine, monkeypatch):
    """Use real independent PG transactions, including commit/rollback on context exit."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    opened = []

    @asynccontextmanager
    async def transaction():
        async with sessions() as db, db.begin():
            opened.append(db)
            yield db

    monkeypatch.setattr(saved_sessions, "get_db_context", transaction)
    return sessions, opened


@pytest.mark.parametrize(
    "field",
    ["organization_id", "user_id", "agent_id", "origin", "secret_id", "expired"],
)
async def test_sealed_provenance_cannot_widen_the_current_restore_audience(saved, field):
    b, state, row = saved
    payload = state.model_dump(mode="json")
    provenance = payload["provenance"]
    if field == "origin":
        provenance["origin"] = "https://another.example.test"
    elif field == "expired":
        provenance["created_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        provenance["expires_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    else:
        provenance[field] = str(uuid4())
        if field == "secret_id":
            provenance["credential_generations"][0]["secret_id"] = provenance[field]
    # The seal belongs to this row's real person/org. Its private payload still
    # owes independent provenance and lifetime checks before anything is returned.
    ProtectedSignIn.model_validate(payload)
    await replace_payload(b, row, payload)
    ciphertext = row.sealed_state
    with pytest.raises(BrowserContinuationRefused) as caught:
        await saved_sessions.load_protected(b.db, b.ctx, b.identity, ORIGIN)
    assert caught.value.reason == BrowserContinuationReason.AUTHORITY_CHANGED
    assert PRIVATE not in str(caught.value)
    await b.db.refresh(row)
    assert row.sealed_state == ciphertext and row.last_used_at is None


@pytest.mark.parametrize("invalid", ["oversized", "malformed"])
async def test_unreadable_sealed_state_never_leaves_a_used_receipt(saved, invalid):
    b, state, row = saved
    payload = state.model_dump(mode="json")
    if invalid == "oversized":
        cookie = dict(payload["cookies"][0], value="synthetic-private-cookie-" * 160)
        payload["cookies"] = [cookie] * 25
        ProtectedSignIn.model_validate(payload)
        assert len(json.dumps(payload).encode("utf-8")) > MAX_SESSION_BYTES + 16_384
    else:
        payload["cookies"] = "not a protected cookie sequence"
    await replace_payload(b, row, payload)
    with pytest.raises(BrowserContinuationRefused) as caught:
        await saved_sessions.load_protected(b.db, b.ctx, b.identity, ORIGIN)
    assert caught.value.reason == BrowserContinuationReason.AUTHORITY_CHANGED
    assert "synthetic-private-cookie" not in str(caught.value)
    await b.db.refresh(row)
    assert row.last_used_at is None


async def test_an_unbound_nonfinal_contributor_cannot_be_restored(saved):
    b, state, row = saved
    payload = state.model_dump(mode="json")
    payload["provenance"]["credential_generations"].append(
        {"secret_id": str(uuid4()), "authorization_generation": str(uuid4())}
    )
    payload["provenance"]["credential_generations"].sort(key=lambda item: UUID(item["secret_id"]))
    ProtectedSignIn.model_validate(payload)
    await replace_payload(b, row, payload)
    with pytest.raises(BrowserContinuationRefused) as caught:
        await saved_sessions.load_protected(b.db, b.ctx, b.identity, ORIGIN)
    assert caught.value.reason == BrowserContinuationReason.AUTHORITY_CHANGED
    await b.db.refresh(row)
    assert row.last_used_at is None


async def test_same_host_does_not_grant_a_contributor_another_https_port(saved):
    b, state, row = saved
    original = urlsplit(ORIGIN)
    port = 9443 if original.port == 8443 else 8443
    destination = f"https://{original.hostname}:{port}"
    payload = state.model_dump(mode="json")
    payload["provenance"]["origin"] = destination
    ProtectedSignIn.model_validate(payload)
    await replace_payload(b, row, payload)
    with pytest.raises(BrowserContinuationRefused) as caught:
        await saved_sessions.load_protected(b.db, b.ctx, b.identity, destination)
    assert caught.value.reason == BrowserContinuationReason.AUTHORITY_CHANGED
    await b.db.refresh(row)
    assert row.last_used_at is None


@pytest.mark.parametrize("change", ["forgotten", "replaced", "ordinary"])
async def test_a_saved_row_changed_before_its_lock_cannot_release_the_earlier_state(
    saved, engine, monkeypatch, change
):
    b, state, row = saved
    row_id = row.id
    replacement = sealed_payload(b, state.model_dump(mode="json"))
    await b.db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    real_get = saved_sessions.repo.get
    changed = False

    async def replace_before_lock(db, sign_in_id, **scope):
        nonlocal changed
        if scope.get("locked") and not changed:
            changed = True
            # A second connection wins before the loader acquires the saved-row
            # lock. Reusing its earlier ORM instance would miss this committed write.
            async with sessions() as other, other.begin():
                if change == "forgotten":
                    await other.execute(delete(BrowserSignIn).where(BrowserSignIn.id == row_id))
                else:
                    values = (
                        {"protection_kind": "manual"}
                        if change == "ordinary"
                        else {
                            "sealed_state": replacement.ciphertext,
                            "secret_key_version": replacement.key_version,
                        }
                    )
                    await other.execute(
                        update(BrowserSignIn).where(BrowserSignIn.id == row_id).values(**values)
                    )
        return await real_get(db, sign_in_id, **scope)

    monkeypatch.setattr(saved_sessions.repo, "get", replace_before_lock)
    with pytest.raises(BrowserContinuationRefused) as caught:
        await saved_sessions.load_protected(b.db, b.ctx, b.identity, ORIGIN)
    assert changed and caught.value.reason == BrowserContinuationReason.AUTHORITY_CHANGED
    await b.db.rollback()
    async with sessions() as verify:
        stored = await verify.get(BrowserSignIn, row_id)
        if change == "forgotten":
            assert stored is None
        else:
            assert stored is not None and stored.last_used_at is None
            assert (stored.protection_kind == "manual") is (change == "ordinary")


@pytest.mark.parametrize(
    "field,value",
    [
        ("credential_ids", ()),
        ("organization_id", None),
        ("run_id", None),
        ("agent_id", None),
        ("impersonated", True),
        ("delegated", True),
        ("audience", None),
        ("run_person", None),
        ("user_id", "another-person"),
        ("audience.browses_signed_in", False),
        ("audience.shared_transcript", True),
        ("audience.user_id", None),
    ],
)
async def test_nonpersonal_context_never_opens_a_saved_state_transaction(
    saved, restore_transactions, field, value
):
    b, _state, row = saved
    deps = admitted_deps(b)
    credential_ids = b.identity.credential_ids
    if field == "credential_ids":
        credential_ids = value
    elif field.startswith("audience."):
        deps.audience = replace(deps.audience, **{field.split(".")[1]: value})
    else:
        setattr(deps, field, value)
    async with saved_sessions.protected_restore(
        deps, credential_ids, "restore-tab", "restore-call", ORIGIN
    ) as result:
        assert result is None
    assert restore_transactions[1] == []
    await b.db.refresh(row)
    assert row.last_used_at is None


async def test_membership_removed_before_restore_never_releases_saved_state(
    saved, restore_transactions
):
    b, _state, row = saved
    deps, credential_ids, row_id = admitted_deps(b), b.identity.credential_ids, row.id
    await b.db.execute(
        delete(OrganizationMember).where(
            OrganizationMember.organization_id == b.org.id,
            OrganizationMember.user_id == b.owner.id,
        )
    )
    await b.db.commit()
    with pytest.raises(BrowserContinuationRefused) as caught:
        async with saved_sessions.protected_restore(
            deps, credential_ids, "restore-tab", "restore-call", ORIGIN
        ):
            pytest.fail("A former member received a protected restore")
    assert caught.value.reason == BrowserContinuationReason.AUTHORITY_CHANGED
    sessions, opened = restore_transactions
    assert len(opened) == 1
    async with sessions() as verify:
        assert (await verify.get(BrowserSignIn, row_id)).last_used_at is None


async def test_private_restore_without_a_saved_row_yields_no_state(browser, restore_transactions):
    b = browser
    deps, credential_ids = admitted_deps(b), b.identity.credential_ids
    await b.db.commit()
    async with saved_sessions.protected_restore(
        deps, credential_ids, "restore-tab", "restore-call", ORIGIN
    ) as state:
        assert state is None
    assert len(restore_transactions[1]) == 1


async def test_restore_retains_run_credential_and_saved_row_locks_until_its_final_check(
    saved, restore_transactions
):
    b, state, row = saved
    deps, credential_ids = admitted_deps(b), b.identity.credential_ids
    locked_rows = [(AgentRun, b.run.id), (OrganizationSecret, b.secret.id), (BrowserSignIn, row.id)]
    row_id = row.id
    await b.db.commit()
    sessions, _opened = restore_transactions
    async with saved_sessions.protected_restore(
        deps, credential_ids, "restore-tab", "restore-call", ORIGIN
    ) as restored:
        assert restored == state and restored.provenance.output_protected is True
        for model, row_key in locked_rows:
            async with sessions() as other:
                with pytest.raises(DBAPIError) as caught:
                    await other.execute(
                        select(model.id).where(model.id == row_key).with_for_update(nowait=True)
                    )
                assert caught.value.orig.sqlstate == "55P03"
    async with sessions() as verify:
        for model, row_key in locked_rows:
            assert (
                await verify.scalar(
                    select(model.id).where(model.id == row_key).with_for_update(nowait=True)
                )
            ) == row_key
        assert (await verify.get(BrowserSignIn, row_id)).last_used_at is not None


@pytest.mark.parametrize("change", ["forgotten", "replaced"])
async def test_restore_cannot_commit_if_its_own_transaction_changes_the_saved_state(
    saved, restore_transactions, change
):
    """The post-yield check also fences changes within the caller's unit of work."""
    b, state, row = saved
    deps, credential_ids, row_id = admitted_deps(b), b.identity.credential_ids, row.id
    original_ciphertext = row.sealed_state
    replacement_payload = state.model_dump(mode="json")
    replacement_payload["cookies"][0]["value"] = "different synthetic protected cookie"
    replacement = sealed_payload(b, replacement_payload)
    await b.db.commit()
    sessions, opened = restore_transactions
    with pytest.raises(BrowserContinuationRefused) as caught:
        async with saved_sessions.protected_restore(
            deps, credential_ids, "restore-tab", "restore-call", ORIGIN
        ) as restored:
            assert restored == state
            current = await opened[-1].get(BrowserSignIn, row_id)
            assert current is not None
            if change == "forgotten":
                await opened[-1].delete(current)
            else:
                current.sealed_state = replacement.ciphertext
                current.secret_key_version = replacement.key_version
            await opened[-1].flush()
    assert caught.value.reason == BrowserContinuationReason.AUTHORITY_CHANGED
    async with sessions() as verify:
        stored = await verify.get(BrowserSignIn, row_id)
        assert stored is not None and stored.sealed_state == original_ciphertext
        assert stored.last_used_at is None
