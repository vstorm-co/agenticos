"""Lifecycle operations use existing API admission and domain services.

Credentials are referenced, never supplied to these tools. Console setup links
leave credential entry and OAuth consent with the person in their own session.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal
from uuid import UUID

from fastmcp.exceptions import ToolError
from pydantic import Field, JsonValue, TypeAdapter

from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.eval_run import EvalRunRequest
from app.schemas.eval_suite import EvalSuiteCreate, EvalSuiteEstimateRequest, EvalSuiteUpdate
from app.schemas.local_service import LocalServiceCreate
from app.schemas.model_profile import ModelProfileCreate, ModelProfileUpdate
from app.schemas.solution import Key
from app.schemas.sync_source import SyncSourceCreate
from app.services.platform_mcp._api import PlatformApi
from app.services.platform_mcp._disclosure import listing, metadata

type Operation = tuple[str, Callable[..., Awaitable[dict[str, JsonValue]]], bool]
_OBJECT = TypeAdapter(dict[str, JsonValue])
Limit = Annotated[int, Field(ge=1, le=50)]
Skip = Annotated[int, Field(ge=0)]


def lifecycle_operations(api: PlatformApi) -> tuple[Operation, ...]:
    """Bind discovery, dependency setup and release operations to the caller."""

    async def call(
        method: str,
        path: str,
        *,
        body: dict[str, JsonValue] | None = None,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, JsonValue]:
        return _OBJECT.validate_python(await api.request(method, path, json=body, params=params))

    async def plan_solution(manifest: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Validate and fingerprint a resource bundle without writing or spending. Needs `agents:view`.

        Returns logical resource keys and required permissions. External model,
        connection and embedding IDs must belong to this deployment. Review the
        exact manifest; install_solution needs this returned manifest_hash.
        """
        return await call("POST", "/solutions/plan", body=manifest)

    async def install_solution(installation: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Install a reviewed bundle as private drafts in one transaction.

        Needs every permission returned by plan_solution. Creates context,
        skills, optional knowledge bases, datasets, agents and workflows with
        optional tables. Publishes, runs and indexes nothing. The same installation
        key and manifest replay the receipt; a changed payload is refused.
        For a prepared review pass plan_id, installation_key and expected_manifest_hash;
        legacy callers may supply manifest instead of plan_id. The receipt records
        installation, not current readiness after later edits.
        Read resources back, test, share and publish as separate authorized steps.
        """
        path = "/solutions/install-plan" if "plan_id" in installation else "/solutions/install"
        return await call("POST", path, body=installation)

    async def prepare_solution(manifest: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Prepare a private 24-hour review so install_solution need not resend a manifest.

        Read get_authoring_schema(contract="solution") first. Needs agents:edit;
        creates only a bounded temporary review, no solution resources or spend.
        Review resources, permissions and manifest_hash, then install_solution with
        plan_id, installation_key and expected_manifest_hash. After expiry/cache
        loss, prepare the same manifest again and reuse the installation key.
        """
        return await call("POST", "/solutions/prepare", body=manifest)

    async def get_solution_installation(installation_key: Key) -> dict[str, JsonValue]:
        """Read your own historical installation identities after an uncertain write. Needs agents:edit.

        This is history, not resource readiness or a grant. Inspect a large /resources
        map with read_platform_details; every live resource read checks access again.
        """
        return await call("GET", f"/solutions/installations/{installation_key}")

    async def get_platform_context() -> dict[str, JsonValue]:
        """Read server version, MCP contract, authentication type and granted token scopes.

        Use before setup or release work. Feature availability is not permission:
        every operation still rechecks the caller's live access and resource grants.
        """
        return await call("GET", "/me/platform-context")

    async def get_setup_link(
        resource: Literal["secret", "model", "embedding", "mcp", "sandbox"],
    ) -> dict[str, JsonValue]:
        """Get the console path for a person to configure a dependency securely.

        Read-only: creates nothing and grants nothing. Open on the connected
        deployment's console, select the same organization, enter secrets or
        approve OAuth there, then rediscover the resource. Never paste tokens,
        callback URLs or passwords into this conversation.
        """
        paths = {
            "secret": "/vault",
            "model": "/agents",
            "embedding": "/kb",
            "mcp": "/mcp-servers",
            "sandbox": "/sandboxes",
        }
        identity = await call("GET", "/me/permissions")
        return {
            "organization_id": identity["organization_id"],
            "console_path": paths[resource],
            "setup_required": True,
            "instruction": "Finish setup in your own console session, then list the resource again.",
        }

    async def list_secret_references(
        q: str | None = None, limit: Limit = 10, skip: Skip = 0, detailed: bool = False
    ) -> dict[str, JsonValue]:
        """List accessible vault IDs, names, kinds and purposes; never values or hints.

        Needs `secrets:view`. Pick an existing matching reference for a model,
        embedding or source. Use get_setup_link when a person must add a key.
        """
        return listing(
            await call("GET", "/secrets/references"),
            q=q,
            limit=limit,
            skip=skip,
            local=True,
            detailed=detailed,
        )

    async def list_model_providers(
        q: str | None = None, limit: Limit = 10, skip: Skip = 0, detailed: bool = False
    ) -> dict[str, JsonValue]:
        """Search provider metadata. Read get_model_provider for its API/region/credential contract. Needs agents:view."""
        return listing(
            await call("GET", "/providers/catalog"),
            q=q,
            limit=limit,
            skip=skip,
            local=True,
            detailed=detailed,
        )

    async def create_model_profile(profile: ModelProfileCreate) -> dict[str, JsonValue]:
        """Create a model profile using an existing secret ID or a keyless endpoint.

        Needs `connections:manage` and access to the referenced secret. Read the
        provider catalog first. No key value is accepted; endpoint checks and
        credential ownership are enforced by the existing model service.
        """
        return await call("POST", "/providers/model-profiles", body=profile.model_dump(mode="json"))

    async def update_model_profile(
        profile_id: UUID, changes: ModelProfileUpdate
    ) -> dict[str, JsonValue]:
        """Change a profile in place; every bound agent sees it on its next run.

        Needs `connections:manage`. Omitted fields stay; explicit nulls follow
        the model profile contract. Describe the shared impact before applying.
        """
        return await call(
            "PATCH",
            f"/providers/model-profiles/{profile_id}",
            body=changes.model_dump(mode="json", exclude_unset=True),
        )

    async def list_embedding_endpoints(
        q: str | None = None, limit: Limit = 10, skip: Skip = 0, detailed: bool = False
    ) -> dict[str, JsonValue]:
        """List accessible local services, including embedding endpoints and their IDs.

        Needs `connections:view`. Select an active service with kind `embedding`
        and the intended provider; an OCR service cannot embed documents.
        """
        return listing(
            await call("GET", "/local-services"),
            q=q,
            limit=limit,
            skip=skip,
            local=True,
            detailed=detailed,
        )

    async def create_embedding_endpoint(service: LocalServiceCreate) -> dict[str, JsonValue]:
        """Register an organization-owned keyless embedding endpoint.

        Needs `connections:manage`. Only kind `embedding`, deployment_wide false
        is accepted here. Existing URL and private-network checks apply.
        """
        if service.kind != "embedding" or service.deployment_wide:
            raise ToolError(
                "Create an organization-owned embedding service; deployment-wide setup uses the console."
            )
        return await call("POST", "/local-services", body=service.model_dump(mode="json"))

    async def get_knowledge_base(kb_id: UUID) -> dict[str, JsonValue]:
        """Read a knowledge base and its embedding configuration. Needs access to it."""
        return await call("GET", f"/kb/{kb_id}")

    async def list_knowledge_documents(
        kb_id: UUID, limit: Limit = 10, skip: Skip = 0
    ) -> dict[str, JsonValue]:
        """Read document identities and indexing states. Needs read access to the base.

        Follow total with skip. A successful upload is not successful indexing.
        """
        return await call("GET", f"/kb/{kb_id}/documents", params={"limit": limit, "skip": skip})

    async def get_knowledge_ingestion(kb_id: UUID) -> dict[str, JsonValue]:
        """Read indexing completion and failures across the base, not just one page."""
        return await call("GET", f"/kb/{kb_id}/ingestion")

    async def list_knowledge_connectors(
        kb_id: UUID, q: str | None = None, limit: Limit = 10, skip: Skip = 0, detailed: bool = False
    ) -> dict[str, JsonValue]:
        """Search connector metadata; read get_knowledge_connector for one configuration schema."""
        return listing(
            await call("GET", f"/kb/{kb_id}/sync-sources/connectors"),
            q=q,
            limit=limit,
            skip=skip,
            local=True,
            detailed=detailed,
        )

    async def list_knowledge_sources(
        kb_id: UUID, q: str | None = None, limit: Limit = 10, skip: Skip = 0, detailed: bool = False
    ) -> dict[str, JsonValue]:
        """Read configured sync sources. Needs access to the knowledge base."""
        return listing(
            await call("GET", f"/kb/{kb_id}/sync-sources"),
            q=q,
            limit=limit,
            skip=skip,
            local=True,
            detailed=detailed,
        )

    async def create_knowledge_source(
        kb_id: UUID, source: SyncSourceCreate
    ) -> dict[str, JsonValue]:
        """Configure repository or other sync using the discovered connector schema.

        Needs edit access to the base and referenced credential. Config contains
        settings only, never credentials; secret_id points to an accessible vault
        reference. A schedule enables recurring ingestion, so state it first.
        """
        return await call("POST", f"/kb/{kb_id}/sync-sources", body=source.model_dump(mode="json"))

    async def sync_knowledge_source(kb_id: UUID, source_id: UUID) -> dict[str, JsonValue]:
        """Queue a source sync. Needs edit access to the base; inspect logs and ingestion afterwards."""
        return await call("POST", f"/kb/{kb_id}/sync-sources/{source_id}/trigger")

    async def list_knowledge_sync_logs(
        kb_id: UUID, source_id: UUID, limit: Limit = 10, skip: Skip = 0
    ) -> dict[str, JsonValue]:
        """Read source sync outcomes; queued or running is not completion."""
        return await call(
            "GET",
            f"/kb/{kb_id}/sync-sources/{source_id}/logs",
            params={"limit": limit, "skip": skip},
        )

    async def create_dataset(dataset: DatasetCreate) -> dict[str, JsonValue]:
        """Create a test dataset. Needs `datasets:edit`; private visibility is recommended.

        Adds no cases and calls no model. Add scored expectations before running.
        """
        return await call("POST", "/datasets", body=dataset.model_dump(mode="json"))

    async def get_dataset(dataset_id: UUID) -> dict[str, JsonValue]:
        """Read a dataset's version and scoring configuration through its access policy."""
        return await call("GET", f"/datasets/{dataset_id}")

    async def add_dataset_case(dataset_id: UUID, case: DatasetCaseCreate) -> dict[str, JsonValue]:
        """Add a question with expectations; creates a new dataset version. Needs edit access.

        Read existing cases before retrying an uncertain write; each add is a new case.
        """
        result = await call(
            "POST", f"/datasets/{dataset_id}/cases", body=case.model_dump(mode="json")
        )
        return {
            "dataset_id": str(dataset_id),
            **_OBJECT.validate_python(metadata(result)),
            "read_tool": "get_dataset_case",
        }

    async def list_dataset_cases(
        dataset_id: UUID,
        limit: Limit = 10,
        skip: Skip = 0,
        version: int | None = None,
        detailed: bool = False,
    ) -> dict[str, JsonValue]:
        """Read the current dataset's cases and expectations, following total with skip."""
        result = await call(
            "GET",
            f"/datasets/{dataset_id}/cases",
            params={
                "limit": limit,
                "skip": skip,
                **({"version": version} if version is not None else {}),
            },
        )
        if not detailed:
            rows = result.get("items")
            if isinstance(rows, list):
                summaries: list[JsonValue] = []
                for row in rows:
                    item = _OBJECT.validate_python(row)
                    question = TypeAdapter(str).validate_python(item["input"])
                    summary = _OBJECT.validate_python(metadata(item))
                    summary["input_preview"] = question[:160]
                    summary["input_chars"] = len(question)
                    summaries.append(summary)
                result["items"] = summaries
        return listing(result, limit=limit, skip=skip, detailed=True)

    async def estimate_eval_run(agent_id: UUID, run: EvalRunRequest) -> dict[str, JsonValue]:
        """Price a dataset eval without running a model. Needs agent and dataset access.

        Use the same request for start_eval_run after agreeing the cost. Prefer
        a named test environment and recorded calls; testing can otherwise reach live systems.
        """
        return await call(
            "POST", f"/agents/{agent_id}/eval-runs/estimate", body=run.model_dump(mode="json")
        )

    async def start_eval_run(agent_id: UUID, run: EvalRunRequest) -> dict[str, JsonValue]:
        """Start an estimated eval as a background job. Needs dataset run and agent access.

        Budget admission is rechecked by the eval service. Poll get_eval_run;
        admission does not mean the test passed. Requires OAuth, not an organization API key.
        """
        return await call("POST", f"/agents/{agent_id}/eval-runs", body=run.model_dump(mode="json"))

    async def list_agent_versions(
        agent_id: UUID, limit: Limit = 10, skip: Skip = 0
    ) -> dict[str, JsonValue]:
        """Read publication history before comparing, promoting or rolling back an agent."""
        return await call(
            "GET", f"/agents/{agent_id}/versions", params={"limit": limit, "skip": skip}
        )

    async def get_agent_version(agent_id: UUID, version_id: UUID) -> dict[str, JsonValue]:
        """Read one immutable published spec; get_agent's draft is not the live spec."""
        return await call("GET", f"/agents/{agent_id}/versions/{version_id}")

    async def list_agent_environments(
        agent_id: UUID,
        q: str | None = None,
        limit: Limit = 10,
        skip: Skip = 0,
        detailed: bool = False,
    ) -> dict[str, JsonValue]:
        """Search environment metadata. Read get_agent_environment for test connections and promotion guards."""
        return listing(
            await call("GET", f"/agents/{agent_id}/environments"),
            q=q,
            limit=limit,
            skip=skip,
            local=True,
            detailed=detailed,
        )

    async def create_agent_environment(
        agent_id: UUID, environment: EnvironmentCreate
    ) -> dict[str, JsonValue]:
        """Create a named version pointer with optional test connections. Needs publish access.

        Pin production before publishing a candidate if it currently tracks latest.
        """
        return await call(
            "POST", f"/agents/{agent_id}/environments", body=environment.model_dump(mode="json")
        )

    async def update_agent_environment(
        agent_id: UUID, environment_id: UUID, changes: EnvironmentUpdate
    ) -> dict[str, JsonValue]:
        """Configure, promote or roll back an environment through existing promotion gates.

        Needs publish access. Read the old pointer and the proposed version first.
        A rollback repoints to an existing version, never deletes history. Guard
        changes and overrides retain their stronger permission and human-session
        requirements; this tool does not bypass them. Omitted fields stay unchanged.
        """
        return await call(
            "PATCH",
            f"/agents/{agent_id}/environments/{environment_id}",
            body=changes.model_dump(mode="json", exclude_unset=True),
        )

    async def get_promotion_gate(
        agent_id: UUID, environment_id: UUID, version_id: UUID
    ) -> dict[str, JsonValue]:
        """Read whether every guard passes for this exact version and serving baseline."""
        return await call(
            "GET",
            f"/agents/{agent_id}/environments/{environment_id}/gate",
            params={"version_id": str(version_id)},
        )

    async def run_promotion_gate(
        agent_id: UUID, environment_id: UUID, version_id: UUID
    ) -> dict[str, JsonValue]:
        """Run missing promotion checks; may spend on evals. Poll the gate before promotion.

        Read guarding suites and their estimates first. Existing frozen pins,
        thresholds and budget caps apply; never weaken a guard to force a release.
        """
        return await call(
            "POST",
            f"/agents/{agent_id}/environments/{environment_id}/gate/run",
            body={"version_id": str(version_id)},
        )

    async def list_eval_suites(
        agent_id: UUID,
        q: str | None = None,
        limit: Limit = 10,
        skip: Skip = 0,
        detailed: bool = False,
    ) -> dict[str, JsonValue]:
        """Search suite metadata; read get_eval_suite before changing automatic checks or promotion guards."""
        return listing(
            await call("GET", f"/agents/{agent_id}/eval-suites"),
            q=q,
            limit=limit,
            skip=skip,
            local=True,
            detailed=detailed,
        )

    async def estimate_eval_suite(
        agent_id: UUID, suite: EvalSuiteEstimateRequest
    ) -> dict[str, JsonValue]:
        """Price automatic evals before configuring their triggers, schedule and cap."""
        return await call(
            "POST", f"/agents/{agent_id}/eval-suites/estimate", body=suite.model_dump(mode="json")
        )

    async def create_eval_suite(agent_id: UUID, suite: EvalSuiteCreate) -> dict[str, JsonValue]:
        """Create automatic checks with the caller's authority and chosen spending limit.

        Estimate first and describe unattended triggers. Existing personal-consent
        requirements apply. Needs edit/run access to the agent and dataset.
        """
        return await call(
            "POST", f"/agents/{agent_id}/eval-suites", body=suite.model_dump(mode="json")
        )

    async def update_eval_suite(
        agent_id: UUID, suite_id: UUID, changes: EvalSuiteUpdate
    ) -> dict[str, JsonValue]:
        """Change or pause a suite. Guard weakening retains override authorization.

        Only supplied fields change. The caller becomes the suite's owner under
        the same personal-authority rules as the console.
        """
        return await call(
            "PATCH",
            f"/agents/{agent_id}/eval-suites/{suite_id}",
            body=changes.model_dump(mode="json", exclude_unset=True),
        )

    operations = (
        (plan_solution, False),
        (install_solution, True),
        (prepare_solution, True),
        (get_solution_installation, False),
        (get_platform_context, False),
        (get_setup_link, False),
        (list_secret_references, False),
        (list_model_providers, False),
        (create_model_profile, True),
        (update_model_profile, True),
        (list_embedding_endpoints, False),
        (create_embedding_endpoint, True),
        (get_knowledge_base, False),
        (list_knowledge_documents, False),
        (get_knowledge_ingestion, False),
        (list_knowledge_connectors, False),
        (list_knowledge_sources, False),
        (create_knowledge_source, True),
        (sync_knowledge_source, True),
        (list_knowledge_sync_logs, False),
        (create_dataset, True),
        (get_dataset, False),
        (add_dataset_case, True),
        (list_dataset_cases, False),
        (estimate_eval_run, False),
        (start_eval_run, True),
        (list_agent_versions, False),
        (get_agent_version, False),
        (list_agent_environments, False),
        (create_agent_environment, True),
        (update_agent_environment, True),
        (get_promotion_gate, False),
        (run_promotion_gate, True),
        (list_eval_suites, False),
        (estimate_eval_suite, False),
        (create_eval_suite, True),
        (update_eval_suite, True),
    )

    return tuple((function.__name__, function, writes) for function, writes in operations)
