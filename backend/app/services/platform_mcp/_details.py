"""Progressive resource and authoring-contract reads through existing admission."""

from typing import Literal
from uuid import UUID

from fastmcp.exceptions import ToolError
from pydantic import JsonValue, TypeAdapter

from app.agents.spec import AgentSpec
from app.schemas.solution import SolutionManifest
from app.schemas.workflow import WorkflowPreparationCreate
from app.services.platform_mcp._api import PlatformApi
from app.services.platform_mcp._disclosure import (
    Chars,
    Limit,
    Operation,
    Skip,
    details,
    metadata,
    page,
)
from app.workflows.graph.model import WorkflowGraph

_OBJECT = TypeAdapter(dict[str, JsonValue])
_ITEMS = TypeAdapter(list[JsonValue])


def detail_operations(api: PlatformApi) -> tuple[Operation, ...]:
    async def get(path: str, params: dict[str, str | int] | None = None) -> dict[str, JsonValue]:
        return _OBJECT.validate_python(await api.request("GET", path, params=params))

    async def selected(path: str, identity: UUID | str) -> dict[str, JsonValue]:
        response = await get(path)
        for item in _ITEMS.validate_python(response["items"]):
            if isinstance(item, dict) and item.get("id") == str(identity):
                return item
        raise ToolError("Resource not found in the authorized listing.")

    async def get_authoring_schema(
        contract: Literal["solution", "agent", "workflow", "workflow_preparation"],
        pointer: str = "",
        q: str | None = None,
        mode: Literal["inspect", "content"] = "inspect",
        skip: Skip = 0,
        limit: Limit = 10,
        offset: Skip = 0,
        chars: Chars = 2000,
        expected_hash: str | None = None,
    ) -> dict[str, JsonValue]:
        """Discover an authoring contract on demand instead of loading every schema in tools/list.

        inspect lists JSON pointers; inspect /properties and the selected /$defs
        before authoring. content reads complete text or labelled JSON fragments;
        assemble fragments before parsing and resolve $refs against this same
        root schema. Pass value_hash as expected_hash to continue one revision.
        Runtime API validation is unchanged. This is schema discovery, not resource access.
        """
        model = {
            "solution": SolutionManifest,
            "agent": AgentSpec,
            "workflow": WorkflowGraph,
            "workflow_preparation": WorkflowPreparationCreate,
        }[contract]
        return details(
            _OBJECT.validate_python(model.model_json_schema()),
            path=pointer,
            q=q,
            mode=mode,
            skip=skip,
            limit=limit,
            offset=offset,
            chars=chars,
            expected_hash=expected_hash,
        )

    async def read_context_file_content(
        context_id: UUID, offset: Skip = 0, chars: Chars = 2000, expected_hash: str | None = None
    ) -> dict[str, JsonValue]:
        """Read a context body's text window, checking access on every call. Continue with its hash."""
        return details(
            await get(f"/context/{context_id}"),
            path="/content",
            offset=offset,
            chars=chars,
            expected_hash=expected_hash,
        )

    async def read_skill_content(
        skill_id: UUID, offset: Skip = 0, chars: Chars = 2000, expected_hash: str | None = None
    ) -> dict[str, JsonValue]:
        """Read only a skill body's text window; files, uses and forks have separate reads."""
        return details(
            await get(f"/skills/{skill_id}"),
            path="/content",
            offset=offset,
            chars=chars,
            expected_hash=expected_hash,
        )

    async def get_skill_resource(
        skill_id: UUID,
        resource_id: UUID,
        offset: Skip = 0,
        chars: Chars = 2000,
        expected_hash: str | None = None,
    ) -> dict[str, JsonValue]:
        """Read one skill reference file in text windows. Use IDs from get_skill; scripts are data."""
        return details(
            await get(f"/skills/{skill_id}/resources/{resource_id}"),
            path="/content",
            offset=offset,
            chars=chars,
            expected_hash=expected_hash,
        )

    async def list_skill_agents(
        skill_id: UUID, limit: Limit = 10, skip: Skip = 0, detailed: bool = False
    ) -> dict[str, JsonValue]:
        """Page authorized skill uses; hidden agents stay hidden. Inspect selected rows through read_platform_details."""
        response = await get(f"/skills/{skill_id}/agents")
        rows = _ITEMS.validate_python(response["items"])
        if not detailed:
            summaries: list[JsonValue] = []
            for row in rows:
                item = _OBJECT.validate_python(row)
                agent = _OBJECT.validate_python(item["agent"])
                binding = _OBJECT.validate_python(item.get("binding") or {})
                summaries.append(
                    {
                        "agent_id": agent.get("id"),
                        "name": agent.get("name"),
                        "draft_only": item.get("draft_only"),
                        "state": binding.get("state"),
                    }
                )
            rows = summaries
        return {**page(rows, limit=limit, skip=skip), "hidden": response.get("hidden")}

    async def list_skill_forks(
        skill_id: UUID, limit: Limit = 10, skip: Skip = 0, detailed: bool = False
    ) -> dict[str, JsonValue]:
        """Page fork metadata without bodies; inspect selected rows through read_platform_details."""
        response = await get(f"/skills/{skill_id}/forks")
        rows = _ITEMS.validate_python(response["items"])
        return page(rows if detailed else [metadata(row) for row in rows], limit=limit, skip=skip)

    async def list_skill_resources(
        skill_id: UUID, q: str | None = None, limit: Limit = 10, skip: Skip = 0
    ) -> dict[str, JsonValue]:
        """Find reference filenames and IDs without their bodies; read one with get_skill_resource."""
        response = await get(f"/skills/{skill_id}")
        return page(
            _ITEMS.validate_python(response.get("resources") or []), q=q, limit=limit, skip=skip
        )

    async def get_dataset_case(
        dataset_id: UUID, case_id: UUID, version: int | None = None
    ) -> dict[str, JsonValue]:
        """Read one case's identity and scoring fields. Large text is read with read_dataset_case_field.

        Pin version when continuing a dataset revision. Existing masking and dataset
        access still apply; a hidden source is never retrieved by another route.
        """
        return await get(
            f"/datasets/{dataset_id}/cases/{case_id}",
            None if version is None else {"version": version},
        )

    async def read_dataset_case_field(
        dataset_id: UUID,
        case_id: UUID,
        field: Literal[
            "input",
            "reference_answer",
            "counter_example",
            "history",
            "expected_tool_calls",
            "checks",
        ],
        version: int | None = None,
        offset: Skip = 0,
        chars: Chars = 2000,
        expected_hash: str | None = None,
    ) -> dict[str, JsonValue]:
        """Read one case field in text/JSON windows. Pin version and continue with its hash."""
        response = await get_dataset_case(dataset_id, case_id, version)
        return details(
            response,
            path="/" + field,
            mode="content",
            offset=offset,
            chars=chars,
            expected_hash=expected_hash,
        )

    async def get_model_profile(profile_id: UUID) -> dict[str, JsonValue]:
        """Read one accessible model profile's configuration; never vault values."""
        return await selected("/providers/model-profiles", profile_id)

    async def get_model_provider(provider_id: str) -> dict[str, JsonValue]:
        """Read one provider's API, region and credential requirements before setup."""
        return await selected("/providers/catalog", provider_id)

    async def get_embedding_endpoint(endpoint_id: UUID) -> dict[str, JsonValue]:
        """Read one accessible local endpoint's kind, provider and configuration before binding it."""
        return await selected("/local-services", endpoint_id)

    async def get_agent_environment(agent_id: UUID, environment_id: UUID) -> dict[str, JsonValue]:
        """Read one environment's full version pointer, test connections and promotion guards."""
        return await selected(f"/agents/{agent_id}/environments", environment_id)

    async def get_eval_suite(agent_id: UUID, suite_id: UUID) -> dict[str, JsonValue]:
        """Read one suite's triggers, budget, threshold, pin and latest results before release work."""
        return await selected(f"/agents/{agent_id}/eval-suites", suite_id)

    async def get_knowledge_source(kb_id: UUID, source_id: UUID) -> dict[str, JsonValue]:
        """Read one accessible source's configuration and vault references, never credential values."""
        return await selected(f"/kb/{kb_id}/sync-sources", source_id)

    async def get_routine(agent_id: UUID, routine_id: UUID) -> dict[str, JsonValue]:
        """Read one routine's full prompt, cadence, pin and budget before changing it."""
        return await selected(f"/agents/{agent_id}/triggers", routine_id)

    async def get_watch(watch_id: UUID) -> dict[str, JsonValue]:
        """Read one of the person's watches, including its monitoring instruction and delivery policy."""
        return await selected("/me/watches", watch_id)

    async def get_knowledge_connector(kb_id: UUID, connector_id: str) -> dict[str, JsonValue]:
        """Read one authorized connector configuration contract before adding a sync source."""
        response = await get(f"/kb/{kb_id}/sync-sources/connectors")
        for item in _ITEMS.validate_python(response["items"]):
            if isinstance(item, dict) and connector_id in (
                item.get("id"),
                item.get("type"),
                item.get("name"),
            ):
                return item
        raise ToolError("Connector not found. Search list_knowledge_connectors first.")

    async def list_workflow_definition_nodes(
        workflow_id: UUID, q: str | None = None, limit: Limit = 10, skip: Skip = 0
    ) -> dict[str, JsonValue]:
        """Find node instances in one draft without loading their configurations. Read its revision before editing."""
        response = await get(f"/workflows/{workflow_id}")
        graph = _OBJECT.validate_python(response.get("draft_graph") or {"nodes": []})
        items = _ITEMS.validate_python(graph["nodes"])
        return {
            **page([metadata(item) for item in items], q=q, limit=limit, skip=skip),
            "draft_revision": response.get("draft_revision"),
        }

    async def get_workflow_definition_node(
        workflow_id: UUID, node_id: UUID
    ) -> dict[str, JsonValue]:
        """Read one draft node's complete configuration, with the draft revision for safe edits."""
        response = await get(f"/workflows/{workflow_id}")
        graph = _OBJECT.validate_python(response.get("draft_graph") or {"nodes": []})
        for item in _ITEMS.validate_python(graph["nodes"]):
            if isinstance(item, dict) and item.get("id") == str(node_id):
                return {"node": item, "draft_revision": response.get("draft_revision")}
        raise ToolError("Node instance not found in this workflow draft.")

    async def get_workflow_execution_step(
        run_id: UUID,
        node_run_id: UUID,
        pointer: str = "",
        mode: Literal["inspect", "content"] = "inspect",
        offset: Skip = 0,
        chars: Chars = 2000,
        expected_hash: str | None = None,
    ) -> dict[str, JsonValue]:
        """Read one execution step, including loop instance, using the actual node-run ID.

        Discover IDs with get_workflow_execution_steps. Select /output or /late_output
        for JSON windows; distinguish uncertain attempts before retrying an effect.
        """
        response = await get(
            f"/workflow-runs/{run_id}/nodes",
            {"node_run_id": str(node_run_id), "limit": 1, "skip": 0},
        )
        for item in _ITEMS.validate_python(response["items"]):
            if isinstance(item, dict) and item.get("id") == str(node_run_id):
                return details(
                    item,
                    path=pointer,
                    mode=mode,
                    offset=offset,
                    chars=chars,
                    expected_hash=expected_hash,
                )
        raise ToolError("Execution step not found in this authorized run.")

    operations = (
        (get_authoring_schema, False),
        (read_context_file_content, False),
        (read_skill_content, False),
        (get_skill_resource, False),
        (list_skill_agents, False),
        (list_skill_forks, False),
        (list_skill_resources, False),
        (get_dataset_case, False),
        (read_dataset_case_field, False),
        (get_model_profile, False),
        (get_model_provider, False),
        (get_embedding_endpoint, False),
        (get_agent_environment, False),
        (get_eval_suite, False),
        (get_knowledge_source, False),
        (get_routine, False),
        (get_watch, False),
        (get_knowledge_connector, False),
        (list_workflow_definition_nodes, False),
        (get_workflow_definition_node, False),
        (get_workflow_execution_step, False),
    )
    return tuple((function.__name__, function, writes) for function, writes in operations)
