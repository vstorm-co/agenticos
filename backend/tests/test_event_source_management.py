"""Sources retain vault and resource-grant boundaries across edits and attachment."""

import json
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.vault import VaultScope, seal, unseal
from app.db.models.agent import Agent
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.event_source import EventSource, EventSourceCredential, EventSubscription
from app.db.models.resource_grant import GrantLevel
from app.schemas.event_source import EventSourceUpdate, SourceAuth, SourceCredentials
from app.services import access
from app.services import event_sources as module
from app.services.event_sources import EventSourceService, credential_json

pytestmark = pytest.mark.anyio


@pytest.fixture
def ctx():
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.MEMBER.value)


@pytest.fixture
def source(ctx):
    return EventSource(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="Issues",
        provider="webhook",
        auth=SourceAuth().model_dump(),
        visibility="private",
        delivery_id_header="x-event-id",
        is_active=True,
        secret_id=uuid4(),
    )


@pytest.fixture
def setup(monkeypatch, ctx, source):
    db = AsyncMock()
    saved = []
    envelope = seal(
        credential_json(SourceCredentials(secret=SecretStr("original-secret"))),
        scope=VaultScope.organization(ctx.organization_id),
    )
    credential = EventSourceCredential(
        id=source.secret_id,
        organization_id=ctx.organization_id,
        sealed_secret=envelope.ciphertext,
        secret_key_version=envelope.key_version,
    )

    async def save(_db, row):
        if row.id is None:
            row.id = uuid4()
        saved.append(row)
        return row

    monkeypatch.setattr(module.repo, "get", AsyncMock(return_value=source))
    monkeypatch.setattr(module.repo, "credential", AsyncMock(return_value=credential))
    monkeypatch.setattr(module.repo, "save", AsyncMock(side_effect=save))
    monkeypatch.setattr(module.repo, "list_sources", AsyncMock(return_value=[source]))
    monkeypatch.setattr(module.repo, "subscriptions", AsyncMock(return_value=[]))
    monkeypatch.setattr(module.repo, "target_subscription", AsyncMock(return_value=None))
    monkeypatch.setattr(module.repo, "unbind", AsyncMock())
    monkeypatch.setattr(module, "record_audit", AsyncMock())
    monkeypatch.setattr(access.resource_grant_repo, "get_level", AsyncMock(return_value=None))
    monkeypatch.setattr(access.resource_grant_repo, "list_shared_ids", AsyncMock(return_value=[]))
    return EventSourceService(db), credential, saved


@pytest.mark.security
async def test_credential_replacement_seals_in_the_same_tenant_and_never_audits_values(
    ctx, source, setup
):
    service, credential, saved = setup
    before = credential.sealed_secret
    await service.replace_credentials(
        ctx, source.id, SourceCredentials(secret=SecretStr("replacement-secret"))
    )
    assert credential.sealed_secret != before
    assert "replacement-secret" not in credential.sealed_secret
    opened = unseal(
        credential.sealed_secret,
        scope=VaultScope.organization(ctx.organization_id),
        key_version=credential.secret_key_version,
    )
    assert json.loads(opened) == {"secret": "replacement-secret"}
    assert saved == [credential]
    assert "replacement-secret" not in str(module.record_audit.await_args)
    assert "replacement-secret" not in (await service.read(ctx, source)).model_dump_json()


@pytest.mark.security
async def test_editing_visibility_preserves_credentials_and_source_identity(ctx, source, setup):
    service, credential, saved = setup
    before = credential.sealed_secret
    result = await service.update(
        ctx, source.id, EventSourceUpdate(name="Renamed", visibility="org", is_active=False)
    )
    assert (result.id, result.name, result.visibility, result.is_active) == (
        source.id,
        "Renamed",
        "org",
        False,
    )
    assert credential.sealed_secret == before
    assert saved == [source]
    assert result.webhook_url.endswith(str(source.id))


@pytest.mark.security
async def test_changing_authentication_requires_credentials_that_match_the_new_method(
    ctx, source, setup
):
    service, credential, saved = setup
    before = credential.sealed_secret
    with pytest.raises(BadRequestError, match="Basic Auth"):
        await service.update(ctx, source.id, EventSourceUpdate(auth=SourceAuth(method="basic")))
    assert saved == []
    assert source.auth["method"] == "hmac"
    assert credential.sealed_secret == before
    await service.update(
        ctx,
        source.id,
        EventSourceUpdate(
            auth=SourceAuth(method="basic"),
            credentials=SourceCredentials(
                username=SecretStr("alice"), password=SecretStr("password-value")
            ),
        ),
    )
    assert source.auth["method"] == "basic"
    opened = unseal(
        credential.sealed_secret,
        scope=VaultScope.organization(ctx.organization_id),
        key_version=credential.secret_key_version,
    )
    assert json.loads(opened) == {"username": "alice", "password": "password-value"}


@pytest.mark.security
async def test_missing_vault_record_cannot_be_replaced_under_an_unchecked_id(ctx, source, setup):
    service, _, saved = setup
    module.repo.credential.return_value = None
    with pytest.raises(NotFoundError):
        await service.replace_credentials(
            ctx, source.id, SourceCredentials(secret=SecretStr("new-value"))
        )
    assert saved == []


@pytest.mark.security
@pytest.mark.parametrize(
    "grant,allowed", [(GrantLevel.READ, False), (GrantLevel.USE, True), (GrantLevel.EDIT, True)]
)
async def test_explicit_source_grants_widen_use_without_promoting_a_viewer(
    ctx, source, setup, grant, allowed
):
    service, _, _ = setup
    viewer = replace(ctx, role=OrgRoleName.VIEWER.value, user_id=uuid4())
    access.resource_grant_repo.get_level.return_value = grant
    if allowed:
        assert await service.require_use(viewer, source.id) is source
    else:
        with pytest.raises(NotFoundError):
            await service.require_use(viewer, source.id)
    assert access.resource_grant_repo.get_level.await_args.kwargs["resource_type"] == "event_source"


@pytest.mark.security
async def test_source_listing_filters_private_and_foreign_rows_and_reports_effective_permissions(
    ctx, source, setup
):
    service, _, _ = setup
    other_private = EventSource(
        id=uuid4(), organization_id=ctx.organization_id, owner_user_id=uuid4(), visibility="private"
    )
    foreign = EventSource(
        id=uuid4(), organization_id=uuid4(), owner_user_id=ctx.user_id, visibility="org"
    )
    module.repo.list_sources.return_value = [source, other_private, foreign]
    result = await service.list(ctx)
    assert result.total == 1
    assert result.items[0].id == source.id
    assert result.items[0].can_use and result.items[0].can_edit


@pytest.mark.security
async def test_organization_visibility_allows_use_but_not_another_members_edits(ctx, source, setup):
    service, _, _ = setup
    source.visibility = "org"
    source.owner_user_id = uuid4()
    assert await service.require_use(ctx, source.id) is source
    with pytest.raises(NotFoundError):
        await service.get(ctx, source.id, perm=Perm.EVENT_SOURCES_EDIT)


@pytest.mark.security
async def test_routine_binding_requires_both_target_edit_and_run(ctx, source, setup, monkeypatch):
    service, _, saved = setup
    trigger = AgentTrigger(id=uuid4(), organization_id=ctx.organization_id, agent_id=uuid4())
    target = Agent(
        id=trigger.agent_id,
        organization_id=ctx.organization_id,
        owner_user_id=uuid4(),
        visibility="private",
    )
    monkeypatch.setattr(module.trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    monkeypatch.setattr(module.agent_repo, "get", AsyncMock(return_value=target))
    access.resource_grant_repo.get_level.return_value = GrantLevel.USE
    with pytest.raises(AuthorizationError, match="Editing and running"):
        await service.bind_routine(ctx, source.id, trigger.id)
    assert saved == []
    access.resource_grant_repo.get_level.return_value = GrantLevel.EDIT
    await service.bind_routine(ctx, source.id, trigger.id)
    assert len(saved) == 1 and isinstance(saved[0], EventSubscription)
    assert (saved[0].trigger_id, saved[0].source_id, saved[0].organization_id) == (
        trigger.id,
        source.id,
        ctx.organization_id,
    )


async def test_rebinding_the_same_source_preserves_subscription_and_accepted_dispatches(
    ctx, source, setup, monkeypatch
):
    service, _, saved = setup
    trigger = AgentTrigger(id=uuid4(), organization_id=ctx.organization_id, agent_id=uuid4())
    target = Agent(
        id=trigger.agent_id,
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="private",
    )
    monkeypatch.setattr(module.trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    monkeypatch.setattr(module.agent_repo, "get", AsyncMock(return_value=target))
    subscription = EventSubscription(
        id=uuid4(), organization_id=ctx.organization_id, source_id=source.id, trigger_id=trigger.id
    )
    module.repo.target_subscription.return_value = subscription
    await service.bind_routine(ctx, source.id, trigger.id)
    assert saved == []
    module.repo.unbind.assert_not_awaited()


@pytest.mark.security
async def test_a_source_cannot_attach_a_routine_from_another_tenant(
    ctx, source, setup, monkeypatch
):
    service, _, saved = setup
    trigger = AgentTrigger(id=uuid4(), organization_id=uuid4(), agent_id=uuid4())
    monkeypatch.setattr(module.trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    with pytest.raises(NotFoundError):
        await service.bind_routine(ctx, source.id, trigger.id)
    assert saved == []


@pytest.mark.security
async def test_usage_does_not_disclose_a_private_target_name(ctx, source, setup, monkeypatch):
    service, _, _ = setup
    trigger = AgentTrigger(
        id=uuid4(),
        organization_id=ctx.organization_id,
        agent_id=uuid4(),
        name="Private acquisition",
        is_active=True,
    )
    target = Agent(
        id=trigger.agent_id,
        organization_id=ctx.organization_id,
        owner_user_id=uuid4(),
        visibility="private",
    )
    module.repo.subscriptions.return_value = [EventSubscription(id=uuid4(), trigger_id=trigger.id)]
    monkeypatch.setattr(module.trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    monkeypatch.setattr(module.agent_repo, "get", AsyncMock(return_value=target))
    result = await service.usage(ctx, source.id)
    assert result.items[0].name == "Private routine"
    assert "Private acquisition" not in result.model_dump_json()


@pytest.mark.security
async def test_source_metadata_update_requires_the_current_tenant_vault_record(ctx, source, setup):
    service, _, saved = setup
    module.repo.credential.return_value = None
    with pytest.raises(NotFoundError, match="Source credential not found"):
        await service.update(ctx, source.id, EventSourceUpdate(name="Changed"))
    assert source.name == "Issues"
    assert saved == []
    module.record_audit.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    "change",
    [
        {"auth": SourceAuth(method="provider")},
        {"delivery_id_header": "authorization"},
        {"delivery_id_header": "x-signature-256"},
        {"auth": SourceAuth(method="api_key", header_name="x-event-id")},
    ],
)
async def test_invalid_source_update_is_a_domain_refusal_without_mutating_credentials(
    ctx, source, setup, change
):
    service, credential, saved = setup
    original_ciphertext = credential.sealed_secret
    original_auth = dict(source.auth)
    with pytest.raises(BadRequestError):
        await service.update(ctx, source.id, EventSourceUpdate(**change))
    assert source.auth == original_auth
    assert source.delivery_id_header == "x-event-id"
    assert credential.sealed_secret == original_ciphertext
    assert saved == []
    module.record_audit.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    "credentials",
    [
        SourceCredentials(),
        SourceCredentials(username=SecretStr("alice")),
        SourceCredentials(username=SecretStr(""), password=SecretStr("value")),
        SourceCredentials(username=SecretStr("alice"), password=SecretStr("")),
        SourceCredentials(username=SecretStr("alice:bob"), password=SecretStr("value")),
    ],
)
def test_basic_credentials_refuse_ambiguous_or_empty_identity(credentials):
    with pytest.raises(BadRequestError, match="Basic Auth") as refusal:
        module.prepare_credentials(SourceAuth(method="basic"), credentials, generate=True)
    assert "alice:bob" not in refusal.value.message
    assert "value" not in refusal.value.message


@pytest.mark.security
@pytest.mark.parametrize("method", ["provider", "hmac", "api_key", "standard_webhooks"])
def test_replacing_credentials_never_generates_a_silent_new_key(method):
    with pytest.raises(BadRequestError):
        module.prepare_credentials(SourceAuth(method=method), SourceCredentials(), generate=False)


def test_generated_standard_webhook_key_is_a_valid_32_byte_symmetric_key():
    from app.services.event_source_auth import standard_key

    credentials, reveal = module.prepare_credentials(
        SourceAuth(method="standard_webhooks"), SourceCredentials(), generate=True
    )
    assert reveal is not None and reveal.startswith("whsec_")
    assert credentials.secret.get_secret_value() == reveal
    assert len(standard_key(reveal)) == 32
    same, second_reveal = module.prepare_credentials(
        SourceAuth(method="standard_webhooks"), credentials, generate=False
    )
    assert same.secret == credentials.secret
    assert second_reveal is None


@pytest.mark.security
@pytest.mark.parametrize("visible", [False, True])
async def test_workflow_usage_reports_only_the_name_the_caller_can_view(
    ctx, source, setup, monkeypatch, visible
):
    from app.db.models.workflow import Workflow
    from app.db.models.workflow_exposure import WorkflowExposure

    service, _, _ = setup
    workflow = Workflow(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id if visible else uuid4(),
        visibility="private",
        name="Acquisition plans",
    )
    exposure = WorkflowExposure(
        id=uuid4(), organization_id=ctx.organization_id, workflow_id=workflow.id, is_active=False
    )
    sub = EventSubscription(id=uuid4(), exposure_id=exposure.id)
    module.repo.subscriptions.return_value = [sub]
    monkeypatch.setattr(module.exposure_repo, "get_by_id", AsyncMock(return_value=exposure))
    monkeypatch.setattr(module.workflow_repo, "get", AsyncMock(return_value=workflow))
    result = await service.usage(ctx, source.id)
    assert result.total == 1
    assert result.items[0].kind == "workflow"
    assert result.items[0].name == ("Acquisition plans" if visible else "Private workflow")
    assert not result.items[0].is_active


@pytest.mark.security
@pytest.mark.parametrize("kind", ["routine", "workflow"])
@pytest.mark.parametrize("state", ["removed", "foreign"])
async def test_usage_omits_targets_deleted_or_moved_outside_the_tenant(
    ctx, source, setup, monkeypatch, kind, state
):
    from app.db.models.workflow_exposure import WorkflowExposure

    service, _, _ = setup
    target_id = uuid4()
    if kind == "routine":
        target = None if state == "removed" else AgentTrigger(id=target_id, organization_id=uuid4())
        sub = EventSubscription(id=uuid4(), trigger_id=target_id)
        monkeypatch.setattr(module.trigger_repo, "get_by_id", AsyncMock(return_value=target))
    else:
        target = (
            None if state == "removed" else WorkflowExposure(id=target_id, organization_id=uuid4())
        )
        sub = EventSubscription(id=uuid4(), exposure_id=target_id)
        monkeypatch.setattr(module.exposure_repo, "get_by_id", AsyncMock(return_value=target))
    module.repo.subscriptions.return_value = [sub]
    assert (await service.usage(ctx, source.id)).total == 0


async def test_usage_omits_a_workflow_removed_after_its_entry_was_read(
    ctx, source, setup, monkeypatch
):
    from app.db.models.workflow_exposure import WorkflowExposure

    service, _, _ = setup
    exposure = WorkflowExposure(
        id=uuid4(), organization_id=ctx.organization_id, workflow_id=uuid4()
    )
    module.repo.subscriptions.return_value = [
        EventSubscription(id=uuid4(), exposure_id=exposure.id)
    ]
    monkeypatch.setattr(module.exposure_repo, "get_by_id", AsyncMock(return_value=exposure))
    monkeypatch.setattr(module.workflow_repo, "get", AsyncMock(return_value=None))
    assert (await service.usage(ctx, source.id)).items == []


@pytest.mark.security
@pytest.mark.parametrize(
    "state", ["removed_entry", "foreign_entry", "removed_workflow", "run_only"]
)
async def test_workflow_binding_refuses_missing_target_or_insufficient_authority(
    ctx, source, setup, monkeypatch, state
):
    from app.db.models.workflow import Workflow
    from app.db.models.workflow_exposure import WorkflowExposure

    service, _, saved = setup
    exposure = WorkflowExposure(
        id=uuid4(),
        organization_id=uuid4() if state == "foreign_entry" else ctx.organization_id,
        workflow_id=uuid4(),
    )
    workflow = Workflow(
        id=exposure.workflow_id,
        organization_id=ctx.organization_id,
        owner_user_id=uuid4(),
        visibility="private",
    )
    monkeypatch.setattr(
        module.exposure_repo,
        "get_by_id",
        AsyncMock(return_value=None if state == "removed_entry" else exposure),
    )
    monkeypatch.setattr(
        module.workflow_repo,
        "get",
        AsyncMock(return_value=None if state == "removed_workflow" else workflow),
    )
    access.resource_grant_repo.get_level.return_value = GrantLevel.USE
    error = NotFoundError if state in {"removed_entry", "foreign_entry"} else AuthorizationError
    with pytest.raises(error):
        await service.bind_workflow(ctx, source.id, exposure.id)
    assert saved == []
    module.repo.unbind.assert_not_awaited()


@pytest.mark.parametrize("existing", [False, True])
async def test_workflow_binding_preserves_same_subscription_or_replaces_a_different_source(
    ctx, source, setup, monkeypatch, existing
):
    from app.db.models.workflow import Workflow
    from app.db.models.workflow_exposure import WorkflowExposure

    service, _, saved = setup
    exposure = WorkflowExposure(
        id=uuid4(), organization_id=ctx.organization_id, workflow_id=uuid4()
    )
    workflow = Workflow(
        id=exposure.workflow_id,
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="private",
    )
    monkeypatch.setattr(module.exposure_repo, "get_by_id", AsyncMock(return_value=exposure))
    monkeypatch.setattr(module.workflow_repo, "get", AsyncMock(return_value=workflow))
    sub = EventSubscription(
        id=uuid4(), source_id=source.id if existing else uuid4(), exposure_id=exposure.id
    )
    module.repo.target_subscription.return_value = sub
    await service.bind_workflow(ctx, source.id, exposure.id)
    if existing:
        assert saved == []
        module.repo.unbind.assert_not_awaited()
    else:
        assert len(saved) == 1
        assert (saved[0].source_id, saved[0].exposure_id) == (source.id, exposure.id)
        module.repo.unbind.assert_awaited_once_with(service.db, exposure_id=exposure.id)


@pytest.mark.security
async def test_sharing_cannot_set_unsupported_team_visibility(ctx, source, setup):
    from app.db.models.resource_grant import Visibility
    from app.services.access import EVENT_SOURCE
    from app.services.sharing import SharingService

    service, _, _ = setup
    with pytest.raises(BadRequestError, match="not supported"):
        await SharingService(service.db).set_visibility(
            ctx, source, resource_type=EVENT_SOURCE, visibility=Visibility.TEAM
        )
    assert source.visibility == "private"
