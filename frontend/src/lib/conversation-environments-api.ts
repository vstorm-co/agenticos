import { z } from "zod";

import { apiClient } from "./api-client";

export const environmentKind = z.enum(["browser", "desktop"]);
export type ConversationEnvironmentKind = z.infer<typeof environmentKind>;
const executionTarget = z.enum(["agent", "project"]);
export type EnvironmentExecutionTarget = z.infer<typeof executionTarget>;

const refusalCode = z.enum([
  "capability_not_enabled",
  "connection_unavailable",
  "workspace_unavailable",
  "backend_not_supported",
  "local_device_required",
  "environment_changed",
  "provisioning_failed",
  "environment_expired",
  "capacity_reached",
]);

export const conversationEnvironment = z.object({
  id: z.uuid().nullable(),
  kind: environmentKind,
  execution_target: executionTarget,
  agent_id: z.uuid(),
  state: z.enum(["not_started", "starting", "ready", "failed", "expired"]),
  session_lifetime: z.enum(["run", "conversation"]),
  idle_seconds: z.number().int().nonnegative(),
  control: z.enum(["none", "human", "agent"]),
  can_control: z.boolean(),
  expires_at: z.iso.datetime({ offset: true }).nullable(),
  refusal: z.object({ code: refusalCode, message: z.string() }).nullable(),
});

export type ConversationEnvironment = z.infer<typeof conversationEnvironment>;

const environmentList = z.object({
  items: z
    .array(conversationEnvironment)
    .length(2)
    .refine((items) => new Set(items.map((item) => item.kind)).size === 2),
});

export type ConversationEnvironmentList = z.infer<typeof environmentList>;

function address(conversationId: string, kind?: ConversationEnvironmentKind): string {
  const root = `/conversations/${encodeURIComponent(conversationId)}/environments`;
  return kind === undefined ? root : `${root}/${kind}`;
}

function selection(agentId: string, target: EnvironmentExecutionTarget): string {
  return new URLSearchParams({ agent_id: agentId, project_execution_target: target }).toString();
}

/** Reading readiness never provisions a sandbox or starts an agent run. */
export async function readConversationEnvironments(
  conversationId: string,
  agentId: string,
  target: EnvironmentExecutionTarget = "agent",
): Promise<ConversationEnvironmentList> {
  return environmentList
    .refine((value) =>
      value.items.every((item) => item.agent_id === agentId && item.execution_target === target),
    )
    .parse(
      await apiClient.get<unknown>(`${address(conversationId)}?${selection(agentId, target)}`),
    );
}

/** Idempotently open this person's environment for the current published agent. */
export async function startConversationEnvironment(
  conversationId: string,
  agentId: string,
  kind: ConversationEnvironmentKind,
  target: EnvironmentExecutionTarget = "agent",
): Promise<ConversationEnvironment> {
  return conversationEnvironment
    .refine(
      (value) =>
        value.agent_id === agentId && value.kind === kind && value.execution_target === target,
    )
    .parse(
      await apiClient.post<unknown>(address(conversationId, kind), {
        agent_id: agentId,
        project_execution_target: target,
      }),
    );
}

/** Explicitly end the environment; hiding a panel must never invoke this. */
export async function endConversationEnvironment(
  conversationId: string,
  agentId: string,
  kind: ConversationEnvironmentKind,
  target: EnvironmentExecutionTarget = "agent",
): Promise<void> {
  await apiClient.delete(`${address(conversationId, kind)}?${selection(agentId, target)}`);
}
