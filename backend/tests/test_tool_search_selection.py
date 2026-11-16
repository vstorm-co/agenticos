"""Tool search selects schemas without changing capability execution or disclosure."""

import json
from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset
from pydantic_ai_harness.planning import PlanItem

from app.agents.approval import ApprovalGranted, ApprovalRejected, ApprovalRequest
from app.agents.capabilities._registry import ToolOverride
from app.agents.capabilities.planning import PLANNING_STORE_RESOURCE, new_plan_store
from app.agents.capabilities.planning._capability import WRITE_PLAN_GUIDANCE
from app.agents.capabilities.tool_search import ToolSearchConfig
from app.agents.connect_on_use import (
    ConnectionRequest,
    ConnectOnUse,
    PendingService,
    ServiceOutcome,
)
from app.agents.deps import AgentDeps, ApprovalCallback
from app.agents.factory import BuiltAgent, build_agent
from app.agents.mcp import ApprovalMarked, FittedNames, ToolOrigins, fitted_tool_name
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.secret_kinds import NoSecret
from app.db.models.skill import Skill
from tests.workspaces import document_workspace

pytestmark = pytest.mark.anyio


def _model_spec() -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid4(),
        label="Keyless selection fixture",
        provider="ollama",
        model="fixture",
        params={},
        credential=ResolvedCredential(
            provider="ollama",
            secret=NoSecret(),
            base_url="http://127.0.0.1:11434/v1",
        ),
        fallbacks=[],
    )


def _build(
    config: ToolSearchConfig,
    *,
    capabilities: Sequence[CapabilityBindingSpec] = (),
    toolsets: Sequence[AbstractToolset[AgentDeps]] = (),
    extra_capabilities: Sequence[AbstractCapability[AgentDeps]] = (),
    resources: dict[str, object] | None = None,
    request_approval: ApprovalCallback | None = None,
    agent_id: UUID | None = None,
) -> BuiltAgent:
    return build_agent(
        AgentSpec(
            name="Selection fixture",
            capabilities=[
                *capabilities,
                CapabilityBindingSpec(id="tool_search", config=config.model_dump()),
            ],
        ),
        _model_spec(),
        organization_id=uuid4(),
        agent_id=agent_id,
        extra_toolsets=list(toolsets),
        extra_capabilities=extra_capabilities,
        resources=resources,
        request_approval=request_approval,
    )


def _mcp_toolset(
    prefix: str = "invoices", *, calls: list[str] | None = None, approval: bool = False
) -> AbstractToolset[AgentDeps]:
    """Exercise prefixing, fitting, approval and outer wrappers over a named MCP leaf."""
    toolset = FunctionToolset[AgentDeps](id=f"mcp-{prefix}")

    def fetch_invoice(invoice_id: str) -> str:
        """Fetch one invoice."""
        return f"invoice:{invoice_id}"

    def refund_payment(payment_id: str) -> str:
        """Refund an invoice payment."""
        if calls is not None:
            calls.append(payment_id)
        return f"refunded:{payment_id}"

    toolset.add_function(fetch_invoice, takes_ctx=False)
    toolset.add_function(refund_payment, takes_ctx=False)
    return ToolOrigins(
        ApprovalMarked(
            FittedNames(toolset.prefixed(prefix)),
            policy="all" if approval else "none",
            account="Billing account",
        ),
        connection_id=uuid4(),
        seen={},
    )


async def _visible_names(built: BuiltAgent) -> set[str]:
    offered: list[set[str]] = []

    def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered.append({tool.name for tool in info.function_tools})
        return ModelResponse(parts=[TextPart("done")])

    with built.agent.override(model=FunctionModel(respond)):
        await built.agent.run("Inspect the available tools.", deps=built.deps)
    return offered[0]


@pytest.mark.parametrize("defer_capabilities", [False, True])
@pytest.mark.parametrize("defer_mcp_servers", [False, True])
async def test_each_source_can_be_deferred_independently(
    defer_capabilities: bool, defer_mcp_servers: bool
) -> None:
    built = _build(
        ToolSearchConfig(
            strategy="keywords",
            defer_capabilities=defer_capabilities,
            defer_mcp_servers=defer_mcp_servers,
        ),
        capabilities=[CapabilityBindingSpec(id="charts")],
        toolsets=[_mcp_toolset()],
    )
    expected = set[str]()
    if not defer_capabilities:
        expected.add("create_chart")
    if not defer_mcp_servers:
        expected.update({"invoices_fetch_invoice", "invoices_refund_payment"})
    if defer_capabilities or defer_mcp_servers:
        expected.add("search_tools")

    assert await _visible_names(built) == expected


@pytest.mark.parametrize(
    ("defer_capabilities", "exclude_capabilities"),
    [(False, []), (True, []), (True, ["sandbox"])],
)
async def test_sandbox_child_tools_follow_their_configured_parent_selection(
    defer_capabilities: bool, exclude_capabilities: list[str]
) -> None:
    built = _build(
        ToolSearchConfig(
            strategy="keywords",
            defer_capabilities=defer_capabilities,
            exclude_capabilities=exclude_capabilities,
        ),
        capabilities=[CapabilityBindingSpec(id="sandbox"), CapabilityBindingSpec(id="charts")],
    )
    expected = {"search_tools"} if defer_capabilities else {"create_chart"}
    if not defer_capabilities or "sandbox" in exclude_capabilities:
        expected.update({"ls", "read_file", "glob", "grep", "write_file", "edit_file", "execute"})

    assert await _visible_names(built) == expected


@pytest.mark.parametrize("excluded_name", ["preview_file", "read_file"])
async def test_sandbox_child_tool_exclusions_use_the_binding_renamed_name(
    excluded_name: str,
) -> None:
    built = _build(
        ToolSearchConfig(
            strategy="keywords", defer_capabilities=True, exclude_tools=[excluded_name]
        ),
        capabilities=[
            CapabilityBindingSpec(
                id="sandbox", tool_overrides={"read_file": ToolOverride(name="preview_file")}
            )
        ],
    )
    expected = {"search_tools"}
    if excluded_name == "preview_file":
        expected.add("preview_file")

    assert await _visible_names(built) == expected


async def test_discovered_sandbox_child_tool_executes_in_the_run_workspace() -> None:
    built = _build(
        ToolSearchConfig(strategy="keywords", defer_capabilities=True),
        capabilities=[CapabilityBindingSpec(id="sandbox")],
    )
    workspace = document_workspace()
    offered: list[set[str]] = []

    def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered.append({tool.name for tool in info.function_tools})
        if len(offered) == 1:
            return ModelResponse(parts=[ToolCallPart("search_tools", {"queries": ["write_file"]})])
        if len(offered) == 2:
            write_file = next(tool for tool in info.function_tools if tool.name == "write_file")
            assert write_file.description is not None
            assert "Write" in write_file.description
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "write_file", {"path": "/notes.txt", "content": "saved after discovery"}
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("done")])

    with built.agent.override(model=FunctionModel(respond)):
        await built.agent.run("Save a note.", deps=built.deps, workspace=workspace)

    assert offered[0] == {"search_tools"}
    assert "write_file" in offered[1]
    assert await workspace.read_text("/notes.txt") == "saved after discovery"


async def test_whole_capability_and_wrapped_server_exclusions_leave_other_tools_deferred() -> None:
    built = _build(
        ToolSearchConfig(
            strategy="keywords",
            defer_capabilities=True,
            exclude_capabilities=["charts"],
            exclude_mcp_servers=["invoices"],
        ),
        capabilities=[CapabilityBindingSpec(id="charts"), CapabilityBindingSpec(id="planning")],
        toolsets=[_mcp_toolset(), _mcp_toolset("catalog")],
    )

    assert await _visible_names(built) == {
        "create_chart",
        "invoices_fetch_invoice",
        "invoices_refund_payment",
        "search_tools",
    }


@pytest.mark.parametrize("excluded_name", ["draw_report", "create_chart"])
async def test_capability_tool_exclusions_use_the_binding_renamed_name(excluded_name: str) -> None:
    built = _build(
        ToolSearchConfig(
            strategy="keywords", defer_capabilities=True, exclude_tools=[excluded_name]
        ),
        capabilities=[
            CapabilityBindingSpec(
                id="charts",
                tool_overrides={"create_chart": ToolOverride(name="draw_report")},
            )
        ],
        toolsets=[_mcp_toolset()],
    )
    expected = {"search_tools"}
    if excluded_name == "draw_report":
        expected.add("draw_report")

    assert await _visible_names(built) == expected


@pytest.mark.parametrize("prefix", ["invoices", "billing_" + "account_" * 8])
async def test_mcp_tool_exclusions_use_the_fully_prefixed_and_fitted_name(prefix: str) -> None:
    visible = fitted_tool_name(f"{prefix}_fetch_invoice")
    built = _build(
        ToolSearchConfig(strategy="keywords", exclude_tools=[visible]),
        toolsets=[_mcp_toolset(prefix)],
    )

    assert await _visible_names(built) == {visible, "search_tools"}


@pytest.mark.security
@pytest.mark.parametrize("approved", [False, True])
async def test_discovered_renamed_capability_tool_keeps_its_approval_and_executes(
    approved: bool,
) -> None:
    requested: list[ApprovalRequest] = []

    async def decide(request: ApprovalRequest) -> ApprovalGranted | ApprovalRejected:
        requested.append(request)
        return ApprovalGranted(tool_args=request.tool_args) if approved else ApprovalRejected()

    built = _build(
        ToolSearchConfig(strategy="keywords", defer_capabilities=True),
        capabilities=[
            CapabilityBindingSpec(
                id="charts",
                approval="required",
                tool_overrides={
                    "create_chart": ToolOverride(
                        name="quarterly_report", description="Draw the quarterly revenue report."
                    )
                },
            )
        ],
        request_approval=decide,
    )
    offered: list[set[str]] = []

    def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered.append({tool.name for tool in info.function_tools})
        if len(offered) == 1:
            return ModelResponse(
                parts=[ToolCallPart("search_tools", {"queries": ["quarterly_report"]})]
            )
        if len(offered) == 2:
            chart = next(tool for tool in info.function_tools if tool.name == "quarterly_report")
            assert chart.description == "Draw the quarterly revenue report."
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "quarterly_report",
                        {
                            "chart_type": "bar",
                            "title": "Revenue",
                            "x_values": ["Q1"],
                            "series": [{"key": "revenue", "values": [125]}],
                        },
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("done")])

    with built.agent.override(model=FunctionModel(respond)):
        result = await built.agent.run("Draw the quarterly report.", deps=built.deps)

    assert offered[0] == {"search_tools"}
    assert offered[1:] == [{"quarterly_report", "search_tools"}] * 2
    (request,) = requested
    assert request.capability_id == "charts"
    assert request.capability_tool_id == "create_chart"
    assert request.tool_name == "quarterly_report"
    (returned,) = [
        part
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "quarterly_report"
    ]
    assert isinstance(returned.content, str)
    if approved:
        assert json.loads(returned.content)["data"] == [{"x": "Q1", "revenue": 125.0}]
    else:
        assert "was not performed" in returned.content


@pytest.mark.security
async def test_discovered_mcp_tool_retains_approval_metadata_and_dispatches_to_its_server() -> None:
    calls: list[str] = []
    requested: list[ApprovalRequest] = []

    async def decide(request: ApprovalRequest) -> ApprovalGranted:
        requested.append(request)
        return ApprovalGranted(tool_args=request.tool_args)

    built = _build(
        ToolSearchConfig(strategy="keywords", exclude_tools=["invoices_fetch_invoice"]),
        toolsets=[_mcp_toolset(calls=calls, approval=True)],
        request_approval=decide,
    )
    offered: list[set[str]] = []

    def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered.append({tool.name for tool in info.function_tools})
        if len(offered) == 1:
            return ModelResponse(
                parts=[ToolCallPart("search_tools", {"queries": ["refund_payment"]})]
            )
        if len(offered) == 2:
            return ModelResponse(
                parts=[ToolCallPart("invoices_refund_payment", {"payment_id": "paid-1"})]
            )
        return ModelResponse(parts=[TextPart("done")])

    with built.agent.override(model=FunctionModel(respond)):
        await built.agent.run("Refund paid-1.", deps=built.deps)

    assert offered[0] == {"invoices_fetch_invoice", "search_tools"}
    assert "invoices_refund_payment" in offered[1]
    assert calls == ["paid-1"]
    (request,) = requested
    assert request.capability_id is None
    assert request.account == "Billing account"
    assert request.tool_name == "invoices_refund_payment"


async def test_deferred_capability_tools_keep_instructions_and_reminder_hooks() -> None:
    store = new_plan_store()
    await store.set_items([PlanItem(id="step-1", content="Reconcile the selected invoice")])
    built = _build(
        ToolSearchConfig(strategy="keywords", defer_capabilities=True),
        capabilities=[CapabilityBindingSpec(id="planning")],
        resources={PLANNING_STORE_RESOURCE: store},
    )

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert {tool.name for tool in info.function_tools} == {"search_tools"}
        assert WRITE_PLAN_GUIDANCE in (info.instructions or "")
        assert any(
            isinstance(part, UserPromptPart)
            and "Reconcile the selected invoice" in str(part.content)
            for message in messages
            for part in message.parts
        )
        return ModelResponse(parts=[TextPart("done")])

    with built.agent.override(model=FunctionModel(respond)):
        await built.agent.run("Continue the plan.", deps=built.deps)


async def test_surface_tools_stay_visible_when_both_sources_defer() -> None:
    async def resolve() -> ServiceOutcome:
        return "unreachable"

    async def connect(_request: ConnectionRequest) -> bool:
        return False

    built = _build(
        ToolSearchConfig(strategy="keywords", defer_capabilities=True),
        capabilities=[CapabilityBindingSpec(id="charts")],
        toolsets=[_mcp_toolset()],
        agent_id=uuid4(),
        extra_capabilities=[
            ConnectOnUse(
                services=[
                    PendingService(
                        request=ConnectionRequest(
                            catalog_key="notion", name="Notion", gap="not_connected"
                        ),
                        resolve=resolve,
                    )
                ],
                request_connection=connect,
            )
        ],
    )

    assert await _visible_names(built) == {"connect_account", "request_capability", "search_tools"}


@pytest.mark.parametrize("exclude_skills", [False, True])
async def test_tool_search_preserves_a_skills_read_skill_disclosure_gate(
    exclude_skills: bool,
) -> None:
    secret_instructions = "Refunds require the private procedure approval number."
    skill = Skill(
        id=uuid4(),
        organization_id=uuid4(),
        name="refund-guide",
        description="The private refund procedure.",
        content=secret_instructions,
        resources=[],
    )
    built = _build(
        ToolSearchConfig(
            strategy="keywords",
            defer_capabilities=True,
            exclude_capabilities=["skills"] if exclude_skills else [],
        ),
        capabilities=[CapabilityBindingSpec(id="skills"), CapabilityBindingSpec(id="charts")],
        resources={"skills": [skill]},
    )
    requests = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        assert {tool.name for tool in info.function_tools} == {"read_skill", "search_tools"}
        if requests <= 2:
            assert secret_instructions not in repr(messages)
            assert secret_instructions not in (info.instructions or "")
        if requests == 1:
            return ModelResponse(
                parts=[ToolCallPart("search_tools", {"queries": ["refund-guide"]})]
            )
        if requests == 2:
            return ModelResponse(parts=[ToolCallPart("read_skill", {"id": "refund-guide"})])
        assert secret_instructions in repr(messages)
        return ModelResponse(parts=[TextPart("done")])

    with built.agent.override(model=FunctionModel(respond)):
        await built.agent.run("Read the refund guide.", deps=built.deps)

    assert requests == 3
