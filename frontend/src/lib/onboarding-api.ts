import { z } from "zod";

import { apiClient } from "@/lib/api-client";

export const START_GOALS = ["meeting", "document", "compare"] as const;
export type StartGoal = (typeof START_GOALS)[number];
export type StartStep =
  | `preferences.${"language" | "appearance"}`
  | `admin.${"workspace" | "identity" | "profile" | "context" | "subscriptions" | "models" | "tools" | "team" | "deployment" | "organization" | "task"}`
  | `member.${"welcome" | "profile" | "context" | "subscriptions" | "models" | "tools" | "task"}`;

const agent = z.object({ id: z.uuid(), name: z.string() });
export const START_SCOPES = ["deployment", "organization", "personal"] as const;
export type StartScope = (typeof START_SCOPES)[number];
const scope = z.object({
  scope: z.enum(START_SCOPES),
  applicable: z.boolean(),
  completed: z.boolean(),
  completed_at: z.iso.datetime({ offset: true }).nullable(),
  current_step: z.string().nullable(),
  updated_at: z.iso.datetime({ offset: true }).nullable(),
});
export type StartScopeState = z.infer<typeof scope>;
const scopes = z
  .array(scope)
  .length(3)
  .refine((items) => items.every((item, index) => item.scope === START_SCOPES[index]));
const onboardingBody = z.object({
  server_time: z.iso.datetime({ offset: true }).optional(),
  // Absent only while an older API process serves a rolling upgrade.
  scopes: scopes.optional(),
  active_scope: z.enum(START_SCOPES).nullable().optional(),
  organization_id: z.uuid(),
  organization_name: z.string(),
  goal: z.enum(START_GOALS).nullable(),
  dismissed: z.boolean(),
  completed: z.boolean().default(false),
  current_step: z.string().nullable().optional(),
  updated_at: z.iso.datetime({ offset: true }).nullable().optional(),
  completed_at: z.iso.datetime({ offset: true }).nullable().optional(),
  snoozed_until: z.iso.datetime({ offset: true }).nullable().default(null),
  can_prepare: z.boolean(),
  can_configure_model: z.boolean(),
  support_email: z.string().nullable(),
  agents: z.array(agent),
  setup_agent: agent.nullable().default(null),
  latest_conversation_id: z.uuid().nullable(),
  latest_completed_at: z.string().nullable(),
  has_result: z.boolean(),
  // Older API processes during a rolling upgrade have no activity signal yet.
  has_activity: z.boolean().default(false),
});
function validScopeEnvelope(data: {
  scopes?: StartScopeState[];
  active_scope?: StartScope | null;
}): boolean {
  if (data.scopes === undefined) return data.active_scope === undefined;
  if (data.active_scope === undefined) return false;
  if (data.active_scope === null)
    return !data.scopes.some(
      (scope) => scope.applicable && !scope.completed && scope.scope !== "personal",
    );
  const index = data.scopes.findIndex((scope) => scope.scope === data.active_scope);
  const active = data.scopes[index];
  return (
    active !== undefined &&
    active.applicable &&
    !active.completed &&
    data.scopes.slice(0, index).every((scope) => !scope.applicable || scope.completed)
  );
}
const onboarding = onboardingBody.refine(validScopeEnvelope);
const deploymentOnboarding = onboardingBody
  .extend({
    organization_id: z.null(),
    organization_name: z.null(),
  })
  .refine(validScopeEnvelope);
export type Onboarding = z.infer<typeof onboarding>;
export type DeploymentOnboarding = z.infer<typeof deploymentOnboarding>;
export type StartRead = Onboarding | DeploymentOnboarding;
export interface StartScopeUpdate {
  current_step?: StartStep | null;
  completed?: true;
}
export const parseOnboarding = (value: unknown): Onboarding => onboarding.parse(value);
export interface StartUpdate {
  current_step?: StartStep | null;
  goal?: StartGoal | null;
  dismissed?: boolean;
  completed?: true;
}
export const readDeploymentOnboarding = async () =>
  deploymentOnboarding.parse(await apiClient.get<unknown>("/me/onboarding/deployment"));
export const saveDeploymentOnboarding = async (data: StartScopeUpdate) =>
  deploymentOnboarding.parse(await apiClient.patch<unknown>("/me/onboarding/deployment", data));
export const saveOnboardingScope = async (
  scope: StartScope,
  data: StartScopeUpdate,
  organizationId: string,
) =>
  onboarding.parse(
    await apiClient.patch<unknown>(`/me/onboarding/scopes/${scope}`, data, {
      headers: { "X-Organization-Id": organizationId },
    }),
  );

export const readOnboarding = async () =>
  onboarding.parse(await apiClient.get<unknown>("/me/onboarding"));
export const saveOnboarding = async (data: StartUpdate, organizationId?: string) =>
  onboarding.parse(
    organizationId
      ? await apiClient.patch<unknown>("/me/onboarding", data, {
          headers: { "X-Organization-Id": organizationId },
        })
      : await apiClient.patch<unknown>("/me/onboarding", data),
  );
export const prepareStarter = async (modelId: string, organizationId?: string) =>
  agent.parse(
    organizationId
      ? await apiClient.post<unknown>(
          "/me/onboarding/starter",
          { model_profile_id: modelId },
          { headers: { "X-Organization-Id": organizationId } },
        )
      : await apiClient.post<unknown>("/me/onboarding/starter", { model_profile_id: modelId }),
  );

export function exampleChat(agentId: string, goal: StartGoal): string {
  const query = new URLSearchParams({ with: agentId, new: crypto.randomUUID(), example: goal });
  return `/chat?${query}`;
}
export function startGoal(value: string | null): StartGoal | null {
  return START_GOALS.find((goal) => goal === value) ?? null;
}

export async function previewMemberStart(userId: string): Promise<{ has_common_agent: boolean }> {
  return z
    .object({ has_common_agent: z.boolean() })
    .parse(await apiClient.get<unknown>(`/me/onboarding/members/${encodeURIComponent(userId)}`));
}

/** Ready agents or existing work make the start optional, without inventing a completed run. */
export function shouldOfferStart(
  data: Pick<
    Onboarding,
    "dismissed" | "completed" | "has_result" | "has_activity" | "agents" | "scopes"
  >,
): boolean {
  return (
    (data.scopes?.some(
      (scope) => scope.applicable && !scope.completed && scope.scope !== "personal",
    ) ??
      false) ||
    (!data.dismissed &&
      !data.completed &&
      !data.has_result &&
      !data.has_activity &&
      data.agents.length === 0)
  );
}
