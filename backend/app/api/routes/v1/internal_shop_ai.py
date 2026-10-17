"""Internal Shop AI strangler — full BFF surface on multi-agent until D3."""

from typing import Annotated, Any
from uuid import UUID

from collections.abc import AsyncIterator

from fastapi import APIRouter, File, Header, Query, Request, UploadFile, status
from starlette.responses import StreamingResponse

from app.api.deps import DBSession, RAGDocumentSvc, ValidAPIKey, VectorStoreSvc
from app.core.permissions import AuthContext
from app.core.exceptions import BadRequestError
from app.schemas.shop_ai_mcp import (
    ShopMcpCatalogList,
    ShopMcpConnectionCreate,
    ShopMcpConnectionList,
    ShopMcpConnectionRead,
    ShopMcpConnectionTestResult,
    ShopMcpConnectionUpdate,
)
from app.schemas.shop_merchant_assistant import (
    ShopMerchantAssistantChatIn,
    ShopMerchantAssistantChatOut,
)
from app.schemas.shop_widget import ShopWidgetChatIn, ShopWidgetChatOut, ShopWidgetPollOut
from app.schemas.shop_widget_quality import (
    ShopChatQualityReportRead,
    ShopChatQualitySummaryRead,
)
from app.schemas.knowledge_base import KnowledgeBaseList, KnowledgeBaseRead
from app.schemas.rag import RAGIngestResponse, RAGTrackedDocumentList
from app.schemas.shop_kb_delete import ShopKbDeleteResult
from app.schemas.shop_knowledge_base import ShopKnowledgeBaseCreate
from app.schemas.shop_assistant_persona import (
    ShopAssistantPersonaPatch,
    ShopAssistantPersonaRead,
)
from app.schemas.shop_faq_settings import ShopFaqSettingsPatch, ShopFaqSettingsRead
from app.schemas.shop_faq import (
    ShopFaqEntryCreate,
    ShopFaqEntryList,
    ShopFaqEntryRead,
    ShopFaqEntryUpdate,
    ShopFaqInboxPromoteIn,
    ShopFaqSuggestionAccept,
    ShopFaqSuggestionList,
    ShopFaqSuggestionRead,
)
from app.schemas.shop_live_agent_analytics import ShopLiveAgentAnalyticsReportRead
from app.schemas.shop_live_agent_inbox import ShopLiveAgentInboxSummaryRead
from app.schemas.shop_live_agent_settings import (
    ShopLiveAgentSettingsPatch,
    ShopLiveAgentSettingsRead,
)
from app.schemas.shop_widget_conversation import (
    ShopWidgetConversationList,
    ShopWidgetConversationRead,
    ShopWidgetMessageList,
    ShopWidgetMessageRead,
    ShopWidgetStaffClaimIn,
    ShopWidgetStaffReplyIn,
)
from app.services.minerp_tenant_lookup import tenant_context_for_organization
from app.services.multi_agent_shop_proxy import proxy_shop_ai_request
from app.services.shop_ai_mcp_native import (
    create_shop_mcp_connection,
    delete_shop_mcp_connection,
    list_merchant_mcp_catalog,
    list_merchant_mcp_connections,
    list_shop_mcp_catalog,
    list_shop_mcp_connections,
    shop_native_mcp_reads_enabled,
    shop_native_merchant_mcp_reads_enabled,
    test_shop_mcp_connection,
    update_shop_mcp_connection,
)
from app.services.shop_ai_llm_strangler import (
    shop_merchant_llm_strangler_enabled,
    shop_widget_llm_strangler_enabled,
    strangler_merchant_chat,
    strangler_widget_chat,
)
from app.services.shop_merchant_chat_native import (
    format_merchant_chat_sse,
    try_native_merchant_chat,
)
from app.services.shop_widget_conversation_service import (
    ShopWidgetConversationService,
    widget_message_sender_type,
)
from app.services.shop_widget_studio_handling import (
    claim_widget_conversation,
    release_widget_conversation,
    reply_widget_conversation,
)
from app.services.shop_assistant_persona_settings import ShopAssistantPersonaService
from app.services.shop_faq_settings import ShopFaqSettingsService
from app.services.shop_tenant_kb import ShopTenantKnowledgeBaseService
from app.services.shop_tenant_knowledge import require_kb_for_shop_organization
from app.services.shop_faq_suggestion import ShopFaqSuggestionService
from app.services.shop_faq_sync import ShopFaqService
from app.services.shop_live_agent_analytics import ShopLiveAgentAnalyticsService
from app.services.shop_live_agent_inbox import ShopLiveAgentInboxService
from app.services.shop_live_agent_settings import ShopLiveAgentSettingsService
from app.services.shop_widget_quality import ShopWidgetQualityService
from app.services.shop_widget_tenant import require_org_for_shop_tenant
from app.services.shop_widget_chat_native import (
    native_widget_poll,
    try_native_widget_chat,
    widget_poll_use_strangler,
)

router = APIRouter(prefix="/internal/shop-ai", tags=["internal:shop-ai"])


def _parse_tenant_header(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> UUID:
    if not x_tenant_id or not str(x_tenant_id).strip():
        raise BadRequestError(
            message="X-Tenant-Id header is required",
            details={"header": "X-Tenant-Id"},
        )
    try:
        return UUID(str(x_tenant_id).strip())
    except ValueError as exc:
        raise BadRequestError(
            message="X-Tenant-Id must be a UUID",
            details={"header": "X-Tenant-Id"},
        ) from exc


def _parse_optional_org_header(
    x_organization_id: Annotated[str | None, Header(alias="X-Organization-Id")] = None,
) -> UUID | None:
    if not x_organization_id or not str(x_organization_id).strip():
        return None
    try:
        return UUID(str(x_organization_id).strip())
    except ValueError as exc:
        raise BadRequestError(
            message="X-Organization-Id must be a UUID",
            details={"header": "X-Organization-Id"},
        ) from exc


async def _assert_org_matches_tenant(
    db: DBSession,
    *,
    tenant_id: UUID,
    organization_id: UUID | None,
) -> None:
    if organization_id is None:
        return
    ctx = await tenant_context_for_organization(db, organization_id)
    if ctx.minerp_tenant_id != tenant_id:
        raise BadRequestError(
            message="X-Organization-Id does not match X-Tenant-Id",
            details={
                "organization_id": str(organization_id),
                "minerp_tenant_id": str(ctx.minerp_tenant_id),
                "x_tenant_id": str(tenant_id),
            },
        )


@router.get("/mcp/catalog", response_model=ShopMcpCatalogList)
async def shop_mcp_catalog(
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    if shop_native_mcp_reads_enabled():
        return await list_shop_mcp_catalog()
    return await proxy_shop_ai_request(
        request=request, subpath="mcp/catalog", tenant_id=tenant_id
    )


@router.get("/mcp/connections", response_model=ShopMcpConnectionList)
async def shop_mcp_connections(
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    if shop_native_mcp_reads_enabled():
        return await list_shop_mcp_connections(db, tenant_id=tenant_id)
    return await proxy_shop_ai_request(
        request=request, subpath="mcp/connections", tenant_id=tenant_id
    )


@router.get("/merchant/mcp/catalog", response_model=ShopMcpCatalogList)
async def merchant_mcp_catalog(
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    if shop_native_merchant_mcp_reads_enabled():
        return await list_merchant_mcp_catalog()
    return await proxy_shop_ai_request(
        request=request, subpath="merchant/mcp/catalog", tenant_id=tenant_id
    )


@router.get("/merchant/mcp/connections", response_model=ShopMcpConnectionList)
async def merchant_mcp_connections(
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    if shop_native_merchant_mcp_reads_enabled():
        return await list_merchant_mcp_connections(db, tenant_id=tenant_id)
    return await proxy_shop_ai_request(
        request=request, subpath="merchant/mcp/connections", tenant_id=tenant_id
    )


@router.post(
    "/mcp/connections",
    response_model=ShopMcpConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def shop_mcp_connection_create(
    data: ShopMcpConnectionCreate,
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    native = await create_shop_mcp_connection(db, tenant_id=tenant_id, data=data)
    if native is not None:
        return native
    return await proxy_shop_ai_request(
        request=request,
        subpath="mcp/connections",
        tenant_id=tenant_id,
    )


@router.patch("/mcp/connections/{connection_id}", response_model=ShopMcpConnectionRead)
async def shop_mcp_connection_update(
    connection_id: UUID,
    data: ShopMcpConnectionUpdate,
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    native = await update_shop_mcp_connection(
        db,
        tenant_id=tenant_id,
        connection_id=connection_id,
        data=data,
    )
    if native is not None:
        return native
    return await proxy_shop_ai_request(
        request=request,
        subpath=f"mcp/connections/{connection_id}",
        tenant_id=tenant_id,
    )


@router.delete(
    "/mcp/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def shop_mcp_connection_delete(
    connection_id: UUID,
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> None:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    deleted = await delete_shop_mcp_connection(
        db, tenant_id=tenant_id, connection_id=connection_id
    )
    if deleted:
        return None
    await proxy_shop_ai_request(
        request=request,
        subpath=f"mcp/connections/{connection_id}",
        tenant_id=tenant_id,
    )


@router.post(
    "/mcp/connections/{connection_id}/test",
    response_model=ShopMcpConnectionTestResult,
)
async def shop_mcp_connection_test(
    connection_id: UUID,
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    native = await test_shop_mcp_connection(
        db, tenant_id=tenant_id, connection_id=connection_id
    )
    if native is not None:
        return native
    return await proxy_shop_ai_request(
        request=request,
        subpath=f"mcp/connections/{connection_id}/test",
        tenant_id=tenant_id,
    )


@router.post("/merchant-assistant/chat", response_model=ShopMerchantAssistantChatOut)
async def merchant_assistant_chat(
    data: ShopMerchantAssistantChatIn,
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    reply = await try_native_merchant_chat(tenant_id=tenant_id, message=data.message)
    if reply is not None:
        return ShopMerchantAssistantChatOut(reply=reply)
    if shop_merchant_llm_strangler_enabled():
        return await strangler_merchant_chat(
            request=request,
            tenant_id=tenant_id,
            body_json=data.model_dump_json().encode("utf-8"),
            stream=False,
        )
    return ShopMerchantAssistantChatOut(
        reply=(
            "Mình chưa chắc bạn cần gì. Thử hỏi top bán chạy, tra đơn (token/UUID), "
            "hoặc bật SHOP_AI_NATIVE_MERCHANT_LLM_STRANGLER."
        )
    )


@router.post("/merchant-assistant/chat/stream")
async def merchant_assistant_chat_stream(
    data: ShopMerchantAssistantChatIn,
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    reply = await try_native_merchant_chat(tenant_id=tenant_id, message=data.message)
    if reply is not None:

        async def _native_sse() -> AsyncIterator[str]:
            for event in (
                {"type": "started"},
                {"type": "delta", "text": reply},
                {"type": "done", "reply": reply},
            ):
                yield format_merchant_chat_sse(event)

        return StreamingResponse(_native_sse(), media_type="text/event-stream")
    body_bytes = data.model_dump_json().encode("utf-8")
    if shop_merchant_llm_strangler_enabled():
        return await strangler_merchant_chat(
            request=request,
            tenant_id=tenant_id,
            body_json=body_bytes,
            stream=True,
        )
    reply = (
        "Mình chưa chắc bạn cần gì. Thử hỏi top bán chạy hoặc tra đơn (token/UUID)."
    )

    async def _fallback_sse() -> AsyncIterator[str]:
        for event in (
            {"type": "started"},
            {"type": "delta", "text": reply},
            {"type": "done", "reply": reply},
        ):
            yield format_merchant_chat_sse(event)

    return StreamingResponse(_fallback_sse(), media_type="text/event-stream")


@router.post("/widget/chat", response_model=ShopWidgetChatOut)
async def shop_widget_chat(
    data: ShopWidgetChatIn,
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    native = await try_native_widget_chat(tenant_id=tenant_id, data=data, db=db)
    if native is not None:
        return native
    if shop_widget_llm_strangler_enabled():
        return await strangler_widget_chat(
            request=request,
            tenant_id=tenant_id,
            body_json=data.model_dump_json().encode("utf-8"),
        )
    return ShopWidgetChatOut(
        reply=(
            "Mình chưa hiểu rõ câu hỏi. Bạn thử hỏi tên món, shop bán gì, hoặc tra cứu đơn — "
            "hoặc nhắn gặp nhân viên."
        ),
        session_id=data.session_id,
        handling_mode="ai",
    )


@router.get("/widget/poll", response_model=ShopWidgetPollOut)
async def shop_widget_poll(
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    session_id: UUID = Query(...),
    _after: UUID | None = Query(default=None, alias="after", description="Last seen message id"),
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    if not widget_poll_use_strangler():
        return await native_widget_poll(
            session_id=session_id,
            db=db,
            tenant_id=tenant_id,
            after_message_id=_after,
        )
    return await proxy_shop_ai_request(
        request=request,
        subpath="widget/poll",
        tenant_id=tenant_id,
    )


@router.post("/widget/conversations/{conversation_id}/claim", response_model=ShopWidgetConversationRead)
async def claim_widget_conversation_route(
    conversation_id: UUID,
    body: ShopWidgetStaffClaimIn,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    await claim_widget_conversation(
        db,
        organization_id=org.id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        claimed_by_user_id=body.claimed_by_user_id,
        claimed_by_name=body.claimed_by_name,
    )
    return await ShopWidgetConversationService(db).get_conversation_read(
        organization_id=org.id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )


@router.post("/widget/conversations/{conversation_id}/release", response_model=ShopWidgetConversationRead)
async def release_widget_conversation_route(
    conversation_id: UUID,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    await release_widget_conversation(
        db,
        organization_id=org.id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    return await ShopWidgetConversationService(db).get_conversation_read(
        organization_id=org.id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )


@router.post(
    "/widget/conversations/{conversation_id}/reply",
    response_model=ShopWidgetMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def reply_widget_conversation_route(
    conversation_id: UUID,
    body: ShopWidgetStaffReplyIn,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    msg = await reply_widget_conversation(
        db,
        organization_id=org.id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        text=body.text,
    )
    return ShopWidgetMessageRead(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        sender_type=widget_message_sender_type(role=msg.role, model_name=msg.model_name),
        created_at=msg.created_at,
    )


@router.get("/widget/conversations", response_model=ShopWidgetConversationList)
async def list_widget_conversations_route(
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopWidgetConversationService(db).list_conversations(
        organization_id=org.id,
        tenant_id=tenant_id,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/widget/conversations/{conversation_id}/messages",
    response_model=ShopWidgetMessageList,
)
async def list_widget_conversation_messages_route(
    conversation_id: UUID,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopWidgetConversationService(db).list_messages(
        organization_id=org.id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/widget/conversations/{conversation_id}/messages/{message_id}/promote-faq-suggestion",
    response_model=ShopFaqSuggestionRead,
    status_code=status.HTTP_201_CREATED,
)
async def promote_widget_message_to_faq_suggestion_route(
    conversation_id: UUID,
    message_id: UUID,
    body: ShopFaqInboxPromoteIn,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopWidgetConversationService(db).promote_message_to_faq_suggestion(
        organization_id=org.id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=message_id,
        kb_id=body.kb_id,
    )


@router.get(
    "/knowledge-bases/{kb_id}/faq-suggestions",
    response_model=ShopFaqSuggestionList,
)
async def list_faq_suggestions_route(
    kb_id: UUID,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    suggestion_status: str = Query("pending", alias="status", min_length=4, max_length=16),
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopFaqSuggestionService(db).list_suggestions(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        kb_id=kb_id,
        status=suggestion_status,
    )


@router.get("/knowledge-bases", response_model=KnowledgeBaseList)
async def list_knowledge_bases_route(
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopTenantKnowledgeBaseService(db).list_for_shop(
        organization_id=org.id,
    )


@router.post(
    "/knowledge-bases",
    response_model=KnowledgeBaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_base_route(
    body: ShopKnowledgeBaseCreate,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopTenantKnowledgeBaseService(db).create_for_shop(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        data=body,
    )


@router.delete("/knowledge-bases/{kb_id}", response_model=ShopKbDeleteResult)
async def delete_knowledge_base_route(
    kb_id: UUID,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    transfer_to: UUID = Query(..., description="FAQ KB to receive Q&A and suggestions"),
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopTenantKnowledgeBaseService(db).delete(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        kb_id=kb_id,
        transfer_to=transfer_to,
    )


@router.get("/faq-settings", response_model=ShopFaqSettingsRead)
async def get_faq_settings_route(
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopFaqSettingsService(db).get_settings(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
    )


@router.patch("/faq-settings", response_model=ShopFaqSettingsRead)
async def patch_faq_settings_route(
    body: ShopFaqSettingsPatch,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopFaqSettingsService(db).patch_settings(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        data=body,
    )


@router.get("/assistant-persona", response_model=ShopAssistantPersonaRead)
async def get_assistant_persona_route(
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopAssistantPersonaService(db).get_settings(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
    )


@router.patch("/assistant-persona", response_model=ShopAssistantPersonaRead)
async def patch_assistant_persona_route(
    body: ShopAssistantPersonaPatch,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopAssistantPersonaService(db).patch_settings(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        data=body,
    )


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    response_model=RAGTrackedDocumentList,
)
async def list_kb_documents_route(
    kb_id: UUID,
    db: DBSession,
    rag_doc_service: RAGDocumentSvc,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    await require_kb_for_shop_organization(db, organization_id=org.id, kb_id=kb_id)
    return await rag_doc_service.list_for_kb(kb_id=kb_id, skip=skip, limit=limit)


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=RAGIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_kb_document_route(
    kb_id: UUID,
    db: DBSession,
    rag_doc_service: RAGDocumentSvc,
    vector_store: VectorStoreSvc,
    _api_key: ValidAPIKey,
    file: UploadFile = File(...),
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    replace: bool = Query(False),
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    kb = await require_kb_for_shop_organization(db, organization_id=org.id, kb_id=kb_id)
    data = await file.read()
    ctx = AuthContext(
        user_id=None,
        organization_id=org.id,
        role="owner",
        minerp_tenant_id=tenant_id,
    )
    return await rag_doc_service.dispatch_upload(
        ctx=ctx,
        collection=kb,
        file_data=data,
        filename=file.filename or "unknown",
        replace=replace,
        vector_store=vector_store,
        organization_id=org.id,
        knowledge_base_id=kb.id,
    )


@router.get(
    "/knowledge-bases/{kb_id}/faq-entries",
    response_model=ShopFaqEntryList,
)
async def list_faq_entries_route(
    kb_id: UUID,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopFaqService(db).list_entries(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        kb_id=kb_id,
    )


@router.post(
    "/knowledge-bases/{kb_id}/faq-entries",
    response_model=ShopFaqEntryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_faq_entry_route(
    kb_id: UUID,
    body: ShopFaqEntryCreate,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopFaqService(db).create_entry(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        kb_id=kb_id,
        data=body,
    )


@router.patch(
    "/knowledge-bases/{kb_id}/faq-entries/{entry_id}",
    response_model=ShopFaqEntryRead,
)
async def update_faq_entry_route(
    kb_id: UUID,
    entry_id: UUID,
    body: ShopFaqEntryUpdate,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopFaqService(db).update_entry(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        kb_id=kb_id,
        entry_id=entry_id,
        data=body,
    )


@router.delete(
    "/knowledge-bases/{kb_id}/faq-entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_faq_entry_route(
    kb_id: UUID,
    entry_id: UUID,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> None:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    await ShopFaqService(db).delete_entry(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        kb_id=kb_id,
        entry_id=entry_id,
    )


@router.post(
    "/knowledge-bases/{kb_id}/faq-suggestions/{suggestion_id}/dismiss",
    response_model=ShopFaqSuggestionRead,
)
async def dismiss_faq_suggestion_route(
    kb_id: UUID,
    suggestion_id: UUID,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopFaqSuggestionService(db).dismiss(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        kb_id=kb_id,
        suggestion_id=suggestion_id,
    )


@router.post(
    "/knowledge-bases/{kb_id}/faq-suggestions/{suggestion_id}/draft-answer",
    response_model=ShopFaqSuggestionRead,
)
async def draft_faq_suggestion_answer_route(
    kb_id: UUID,
    suggestion_id: UUID,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopFaqSuggestionService(db).draft_answer(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        kb_id=kb_id,
        suggestion_id=suggestion_id,
    )


@router.post(
    "/knowledge-bases/{kb_id}/faq-suggestions/{suggestion_id}/accept",
    response_model=ShopFaqEntryRead,
    status_code=status.HTTP_201_CREATED,
)
async def accept_faq_suggestion_route(
    kb_id: UUID,
    suggestion_id: UUID,
    body: ShopFaqSuggestionAccept,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopFaqSuggestionService(db).accept(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        kb_id=kb_id,
        suggestion_id=suggestion_id,
        data=body,
    )


@router.get("/widget/chat-quality-report", response_model=ShopChatQualityReportRead)
async def get_widget_chat_quality_report_route(
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    days: int = Query(7, ge=1, le=90),
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopWidgetQualityService(db).build_report(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        days=days,
    )


@router.get("/widget/chat-quality-summary", response_model=ShopChatQualitySummaryRead)
async def get_widget_chat_quality_summary_route(
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    days: int = Query(7, ge=1, le=90),
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopWidgetQualityService(db).build_summary(
        organization_id=org.id,
        minerp_tenant_id=tenant_id,
        days=days,
    )


@router.get("/live-agent/inbox-summary", response_model=ShopLiveAgentInboxSummaryRead)
async def get_live_agent_inbox_summary_route(
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopLiveAgentInboxService(db).build_summary(
        organization_id=org.id,
        tenant_id=tenant_id,
    )


@router.get("/live-agent/analytics-report", response_model=ShopLiveAgentAnalyticsReportRead)
async def get_live_agent_analytics_report_route(
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    days: int = Query(7, ge=1, le=90),
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopLiveAgentAnalyticsService(db).build_report(
        organization_id=org.id,
        tenant_id=tenant_id,
        days=days,
    )


@router.get("/live-agent/settings", response_model=ShopLiveAgentSettingsRead)
async def get_live_agent_settings_route(
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopLiveAgentSettingsService(db).get_settings(organization_id=org.id)


@router.patch("/live-agent/settings", response_model=ShopLiveAgentSettingsRead)
async def patch_live_agent_settings_route(
    body: ShopLiveAgentSettingsPatch,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopLiveAgentSettingsService(db).patch_settings(
        organization_id=org.id,
        data=body,
    )


@router.get(
    "/widget/conversations/{conversation_id}/messages/search",
    response_model=ShopWidgetMessageList,
)
async def search_widget_conversation_messages_route(
    conversation_id: UUID,
    db: DBSession,
    _api_key: ValidAPIKey,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(100, ge=1, le=200),
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    org = await require_org_for_shop_tenant(db, tenant_id)
    return await ShopWidgetConversationService(db).search_messages(
        organization_id=org.id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        query=q,
        limit=limit,
    )


@router.api_route(
    "/{subpath:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    response_model=None,
)
async def proxy_shop_ai(
    subpath: str,
    request: Request,
    _api_key: ValidAPIKey,
    db: DBSession,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> Any:
    tenant_id = _parse_tenant_header(x_tenant_id)
    organization_id = _parse_optional_org_header(
        request.headers.get("X-Organization-Id"),
    )
    await _assert_org_matches_tenant(
        db, tenant_id=tenant_id, organization_id=organization_id
    )
    return await proxy_shop_ai_request(
        request=request,
        subpath=subpath,
        tenant_id=tenant_id,
    )
