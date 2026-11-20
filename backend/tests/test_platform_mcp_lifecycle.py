"""Lifecycle adapters preserve typed payloads, refusal semantics and bounded output."""

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastmcp.exceptions import ToolError
from pydantic import JsonValue, ValidationError

from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.eval_run import EvalRunRequest
from app.schemas.eval_suite import EvalSuiteCreate, EvalSuiteEstimateRequest, EvalSuiteUpdate
from app.schemas.local_service import LocalServiceCreate
from app.schemas.model_profile import ModelProfileCreate, ModelProfileUpdate
from app.schemas.solution import SolutionInstall, SolutionManifest
from app.schemas.sync_source import SyncSourceCreate
from app.services.platform_mcp._tools import platform_tools
from app.services.solution import plan_solution

pytestmark = pytest.mark.anyio
IDENTITY = UUID("00000000-0000-4000-8000-000000000001")
PATH_ID = str(IDENTITY)
type Tool = Callable[..., Awaitable[dict[str, JsonValue]]]


@pytest.fixture
def api() -> MagicMock:
    stub = MagicMock()
    stub.credential_id.return_value = "unit-caller"
    stub.request = AsyncMock(return_value={"id": PATH_ID, "organization_id": PATH_ID})
    return stub


def tools(api: MagicMock) -> dict[str, Tool]:
    return {tool.name: tool.function for tool in platform_tools(api)}


@pytest.mark.parametrize(
    ("name", "arguments", "method", "path"),
    [
        ("get_platform_context", {}, "GET", "/me/platform-context"),
        ("list_secret_references", {}, "GET", "/secrets/references"),
        ("list_model_providers", {}, "GET", "/providers/catalog"),
        (
            "create_model_profile",
            {
                "profile": ModelProfileCreate(
                    label="Local",
                    provider="ollama",
                    model="test",
                    base_url="http://model.example/v1",
                )
            },
            "POST",
            "/providers/model-profiles",
        ),
        (
            "update_model_profile",
            {"profile_id": IDENTITY, "changes": ModelProfileUpdate(label="Renamed")},
            "PATCH",
            f"/providers/model-profiles/{PATH_ID}",
        ),
        ("list_embedding_endpoints", {}, "GET", "/local-services"),
        (
            "create_embedding_endpoint",
            {
                "service": LocalServiceCreate(
                    name="Embeddings",
                    kind="embedding",
                    provider="ollama",
                    base_url="http://model.example/v1",
                )
            },
            "POST",
            "/local-services",
        ),
        ("get_knowledge_base", {"kb_id": IDENTITY}, "GET", f"/kb/{PATH_ID}"),
        (
            "list_knowledge_documents",
            {"kb_id": IDENTITY, "skip": 20},
            "GET",
            f"/kb/{PATH_ID}/documents",
        ),
        ("get_knowledge_ingestion", {"kb_id": IDENTITY}, "GET", f"/kb/{PATH_ID}/ingestion"),
        (
            "list_knowledge_connectors",
            {"kb_id": IDENTITY},
            "GET",
            f"/kb/{PATH_ID}/sync-sources/connectors",
        ),
        ("list_knowledge_sources", {"kb_id": IDENTITY}, "GET", f"/kb/{PATH_ID}/sync-sources"),
        (
            "create_knowledge_source",
            {
                "kb_id": IDENTITY,
                "source": SyncSourceCreate(
                    name="Docs",
                    connector_type="git",
                    config={"repo_url": "https://github.com/example/docs"},
                ),
            },
            "POST",
            f"/kb/{PATH_ID}/sync-sources",
        ),
        (
            "sync_knowledge_source",
            {"kb_id": IDENTITY, "source_id": IDENTITY},
            "POST",
            f"/kb/{PATH_ID}/sync-sources/{PATH_ID}/trigger",
        ),
        (
            "list_knowledge_sync_logs",
            {"kb_id": IDENTITY, "source_id": IDENTITY},
            "GET",
            f"/kb/{PATH_ID}/sync-sources/{PATH_ID}/logs",
        ),
        (
            "create_dataset",
            {"dataset": DatasetCreate(name="Questions", visibility="private")},
            "POST",
            "/datasets",
        ),
        ("get_dataset", {"dataset_id": IDENTITY}, "GET", f"/datasets/{PATH_ID}"),
        (
            "add_dataset_case",
            {
                "dataset_id": IDENTITY,
                "case": DatasetCaseCreate(input="Question?", reference_answer="Answer."),
            },
            "POST",
            f"/datasets/{PATH_ID}/cases",
        ),
        ("list_dataset_cases", {"dataset_id": IDENTITY}, "GET", f"/datasets/{PATH_ID}/cases"),
        (
            "estimate_eval_run",
            {"agent_id": IDENTITY, "run": EvalRunRequest(dataset_id=IDENTITY)},
            "POST",
            f"/agents/{PATH_ID}/eval-runs/estimate",
        ),
        (
            "start_eval_run",
            {"agent_id": IDENTITY, "run": EvalRunRequest(dataset_id=IDENTITY, candidate="draft")},
            "POST",
            f"/agents/{PATH_ID}/eval-runs",
        ),
        ("list_agent_versions", {"agent_id": IDENTITY}, "GET", f"/agents/{PATH_ID}/versions"),
        (
            "get_agent_version",
            {"agent_id": IDENTITY, "version_id": IDENTITY},
            "GET",
            f"/agents/{PATH_ID}/versions/{PATH_ID}",
        ),
        (
            "list_agent_environments",
            {"agent_id": IDENTITY},
            "GET",
            f"/agents/{PATH_ID}/environments",
        ),
        (
            "create_agent_environment",
            {
                "agent_id": IDENTITY,
                "environment": EnvironmentCreate(name="staging", version_id=IDENTITY),
            },
            "POST",
            f"/agents/{PATH_ID}/environments",
        ),
        (
            "update_agent_environment",
            {
                "agent_id": IDENTITY,
                "environment_id": IDENTITY,
                "changes": EnvironmentUpdate(version_id=IDENTITY),
            },
            "PATCH",
            f"/agents/{PATH_ID}/environments/{PATH_ID}",
        ),
        (
            "get_promotion_gate",
            {"agent_id": IDENTITY, "environment_id": IDENTITY, "version_id": IDENTITY},
            "GET",
            f"/agents/{PATH_ID}/environments/{PATH_ID}/gate",
        ),
        (
            "run_promotion_gate",
            {"agent_id": IDENTITY, "environment_id": IDENTITY, "version_id": IDENTITY},
            "POST",
            f"/agents/{PATH_ID}/environments/{PATH_ID}/gate/run",
        ),
        ("list_eval_suites", {"agent_id": IDENTITY}, "GET", f"/agents/{PATH_ID}/eval-suites"),
        (
            "estimate_eval_suite",
            {"agent_id": IDENTITY, "suite": EvalSuiteEstimateRequest(dataset_id=IDENTITY)},
            "POST",
            f"/agents/{PATH_ID}/eval-suites/estimate",
        ),
        (
            "create_eval_suite",
            {"agent_id": IDENTITY, "suite": EvalSuiteCreate(name="Check", dataset_id=IDENTITY)},
            "POST",
            f"/agents/{PATH_ID}/eval-suites",
        ),
        (
            "update_eval_suite",
            {
                "agent_id": IDENTITY,
                "suite_id": IDENTITY,
                "changes": EvalSuiteUpdate(is_active=False),
            },
            "PATCH",
            f"/agents/{PATH_ID}/eval-suites/{PATH_ID}",
        ),
    ],
)
async def test_lifecycle_calls_the_scoped_api(
    api: MagicMock, name: str, arguments: dict[str, object], method: str, path: str
) -> None:
    expected = {"id": PATH_ID, "organization_id": PATH_ID}
    if name == "add_dataset_case":
        expected.update(dataset_id=PATH_ID, read_tool="get_dataset_case")
    assert await tools(api)[name](**arguments) == expected
    assert api.request.call_args.args == (method, path)


@pytest.mark.parametrize(
    "resource,path",
    [
        ("secret", "/vault"),
        ("model", "/agents"),
        ("embedding", "/kb"),
        ("mcp", "/mcp-servers"),
        ("sandbox", "/sandboxes"),
    ],
)
async def test_setup_handoff_does_not_accept_or_return_credentials(
    api: MagicMock, resource: str, path: str
) -> None:
    result = await tools(api)["get_setup_link"](resource=resource)
    assert result["console_path"] == path
    assert result["organization_id"] == PATH_ID
    assert result["setup_required"] is True
    assert api.request.call_args.args == ("GET", "/me/permissions")


async def test_partial_updates_preserve_omitted_fields_and_explicit_nulls(api: MagicMock) -> None:
    await tools(api)["update_model_profile"](IDENTITY, ModelProfileUpdate(secret_id=None))
    assert api.request.call_args.kwargs["json"] == {"secret_id": None}
    await tools(api)["update_agent_environment"](
        IDENTITY, IDENTITY, EnvironmentUpdate(version_id=IDENTITY)
    )
    assert api.request.call_args.kwargs["json"] == {"version_id": PATH_ID}
    await tools(api)["update_eval_suite"](IDENTITY, IDENTITY, EvalSuiteUpdate(is_active=False))
    assert api.request.call_args.kwargs["json"] == {"is_active": False}


@pytest.mark.parametrize("kind,wide", [("ocr", False), ("embedding", True)])
@pytest.mark.security
async def test_embedding_tool_refuses_other_kinds_and_deployment_authority(
    api: MagicMock, kind: str, wide: bool
) -> None:
    service = LocalServiceCreate.model_validate(
        {
            "name": "Service",
            "kind": kind,
            "provider": "ollama",
            "base_url": "http://model.example/v1",
            "deployment_wide": wide,
        }
    )
    with pytest.raises(ToolError, match="organization-owned embedding"):
        await tools(api)["create_embedding_endpoint"](service)
    api.request.assert_not_awaited()


async def test_api_refusal_is_not_an_empty_success(api: MagicMock) -> None:
    api.request.side_effect = ToolError("permission refused")
    with pytest.raises(ToolError, match="permission refused"):
        await tools(api)["create_dataset"](DatasetCreate(name="Refused"))


async def test_oversized_contract_is_explicitly_refused(api: MagicMock) -> None:
    api.request.return_value = {"spec": "x" * 65536}
    result = await tools(api)["get_agent_version"](IDENTITY, IDENTITY)
    assert result["read_tool"] == "read_platform_details"


async def test_malformed_response_is_not_silently_coerced(api: MagicMock) -> None:
    api.request.return_value = []
    with pytest.raises(ValidationError):
        await tools(api)["get_platform_context"]()


async def test_solution_tools_carry_the_reviewed_manifest_and_hash(api: MagicMock) -> None:
    manifest = SolutionManifest.model_validate(
        {"name": "reviewed", "contexts": [{"key": "policy", "data": {"name": "Policy"}}]}
    )
    await tools(api)["plan_solution"](manifest.model_dump(mode="json"))
    assert api.request.call_args.args == ("POST", "/solutions/plan")
    request = SolutionInstall(
        installation_key="reviewed",
        manifest=manifest,
        expected_manifest_hash=plan_solution(manifest).manifest_hash,
    )
    await tools(api)["install_solution"](request.model_dump(mode="json"))
    assert api.request.call_args.args == ("POST", "/solutions/install")
    assert api.request.call_args.kwargs["json"] == request.model_dump(mode="json")
