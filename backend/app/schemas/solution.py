"""Portable, draft-only resource bundles. External dependencies stay explicit IDs."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.spec import AgentSpec
from app.schemas.context import ContextFileCreate
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.knowledge_base import KnowledgeBaseCreate
from app.schemas.skill import SkillCreate
from app.schemas.workflow import WorkflowPreparationCreate

Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,47}$")]


class SolutionContext(BaseModel):
    key: Key
    data: ContextFileCreate


class SolutionSkill(BaseModel):
    key: Key
    data: SkillCreate


class SolutionKnowledge(BaseModel):
    key: Key
    data: KnowledgeBaseCreate


class SolutionDataset(BaseModel):
    key: Key
    data: DatasetCreate
    cases: list[DatasetCaseCreate] = Field(default_factory=list, max_length=100)


class SolutionAgent(BaseModel):
    key: Key
    spec: AgentSpec
    context_keys: list[Key] = Field(default_factory=list, max_length=20)
    skill_keys: list[Key] = Field(default_factory=list, max_length=20)
    knowledge_keys: list[Key] = Field(default_factory=list, max_length=20)


class SolutionWorkflow(BaseModel):
    key: Key
    data: WorkflowPreparationCreate


class SolutionManifest(BaseModel):
    """Install creates private drafts only: no publish, run, schedule or ingestion.

    Use a separate installation key for another copy. The same key and manifest
    replay its receipt; a different manifest on that key is a conflict, never an
    overwrite. Configurations use the platform's existing validated schemas.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(default=1, ge=1, le=1)
    name: Key
    contexts: list[SolutionContext] = Field(default_factory=list, max_length=20)
    skills: list[SolutionSkill] = Field(default_factory=list, max_length=20)
    knowledge: list[SolutionKnowledge] = Field(default_factory=list, max_length=20)
    datasets: list[SolutionDataset] = Field(default_factory=list, max_length=20)
    agents: list[SolutionAgent] = Field(default_factory=list, max_length=20)
    workflows: list[SolutionWorkflow] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _references(self) -> SolutionManifest:
        entries = [
            *self.contexts,
            *self.skills,
            *self.knowledge,
            *self.datasets,
            *self.agents,
            *self.workflows,
        ]
        keys = [entry.key for entry in entries]
        if not keys or len(keys) != len(set(keys)):
            raise ValueError("A solution needs resources with distinct logical keys")
        for agent in self.agents:
            for references, available in (
                (agent.context_keys, {item.key for item in self.contexts}),
                (agent.skill_keys, {item.key for item in self.skills}),
                (agent.knowledge_keys, {item.key for item in self.knowledge}),
            ):
                if len(references) != len(set(references)) or not set(references) <= available:
                    raise ValueError(
                        f"Agent {agent.key} has duplicate or unknown resource references"
                    )
        return self


class SolutionPlan(BaseModel):
    name: str
    manifest_hash: str
    required_permissions: list[str]
    resources: list[str]
    publishes: bool = False
    executes: bool = False


class SolutionInstall(BaseModel):
    installation_key: Key
    expected_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: SolutionManifest


class PreparedSolution(SolutionPlan):
    """A private review document, automatically expired from Redis after 24 hours."""

    plan_id: UUID
    expires_at: datetime


class PreparedSolutionInstall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID
    installation_key: Key
    expected_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SolutionResource(BaseModel):
    kind: Literal["context", "skill", "knowledge", "dataset", "agent", "workflow", "table"]
    id: UUID


class SolutionReceipt(BaseModel):
    installation_key: str
    manifest_hash: str
    resources: dict[str, SolutionResource]
    replayed: bool = False
