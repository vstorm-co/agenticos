"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { useAgents, useAllAgentVersions, useWorkflowTables, useWorkflows } from "@/hooks";
import type { NodeInstance } from "@/lib/workflows/types";

/** The agent, table or workflow a step is set to work with, by the id its config pins. */
export type ResourcePin =
  | { kind: "agent"; id: string; versionId: string | null }
  | { kind: "table"; id: string }
  | { kind: "workflow"; id: string };

function stringAt(value: unknown, key: string): string | null {
  if (typeof value !== "object" || value === null || !(key in value)) return null;
  const field = (value as Record<string, unknown>)[key];
  return typeof field === "string" && field !== "" ? field : null;
}

/** What `instance` pins, or null for a step that names no resource or none yet. */
export function resourcePin(instance: NodeInstance): ResourcePin | null {
  const { config } = instance;
  const agentId = stringAt(config.agent, "agent_id");
  if (agentId !== null) {
    return { kind: "agent", id: agentId, versionId: stringAt(config.agent, "version_id") };
  }
  const tableId = stringAt(config.table, "table_id");
  if (tableId !== null) return { kind: "table", id: tableId };
  const workflowId = stringAt(config, "workflow_id");
  if (workflowId !== null) return { kind: "workflow", id: workflowId };
  return null;
}

/**
 * The agent a step runs, as its face: the card's tile shows who answers rather
 * than a generic robot, so two agent steps tell apart at a glance.
 */
export function AgentTile({
  agentId,
  fallback,
  className = "size-8",
}: {
  agentId: string;
  fallback: ReactNode;
  /** The tile's size, matching the icon tile it stands in for. */
  className?: string;
}) {
  const { agents } = useAgents();
  const agent = agents.find((candidate) => candidate.id === agentId);
  if (agent === undefined) return fallback;
  return (
    <AgentAvatar
      agentId={agent.id}
      slug={agent.slug}
      hasAvatar={agent.has_avatar}
      colorSlot={agent.avatar_color}
      size="sm"
      className={className}
    />
  );
}

type Fallback = { fallback: string | null };

function AgentLine({ pin, fallback }: { pin: Extract<ResourcePin, { kind: "agent" }> } & Fallback) {
  const t = useTranslations("workflows");
  const { agents } = useAgents();
  const { versions } = useAllAgentVersions(pin.id);
  const agent = agents.find((candidate) => candidate.id === pin.id);
  if (agent === undefined) return fallback;
  const version = versions.find((candidate) => candidate.id === pin.versionId);
  return version === undefined
    ? agent.name
    : t("cardAgentVersion", { name: agent.name, version: version.version });
}

function TableLine({ id, fallback }: { id: string } & Fallback) {
  const { tables } = useWorkflowTables();
  return tables.find((table) => table.id === id)?.name ?? fallback;
}

function WorkflowLine({ id, fallback }: { id: string } & Fallback) {
  const { workflows } = useWorkflows();
  return workflows.find((workflow) => workflow.id === id)?.name ?? fallback;
}

/**
 * The name of what a step is set to work with - "Lead scorer · v3", "Leads" -
 * for the line under the card's title. While the lists load, or for an id the
 * caller cannot see, `fallback`: what kind of step it is.
 */
export function ResourceLine({ pin, fallback }: { pin: ResourcePin } & Fallback) {
  if (pin.kind === "agent") return <AgentLine pin={pin} fallback={fallback} />;
  if (pin.kind === "table") return <TableLine id={pin.id} fallback={fallback} />;
  return <WorkflowLine id={pin.id} fallback={fallback} />;
}
