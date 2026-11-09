import { z } from "zod";

import { apiClient } from "@/lib/api-client";

export const START_GOALS = ["meeting", "document", "compare"] as const;
export type StartGoal = (typeof START_GOALS)[number];
const agent = z.object({ id: z.uuid(), name: z.string() });
const onboarding = z.object({
  server_time: z.iso.datetime({ offset: true }).optional(),
  organization_id: z.uuid(),
  organization_name: z.string(),
  goal: z.enum(START_GOALS).nullable(),
  dismissed: z.boolean(),
  completed: z.boolean().default(false),
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
export type Onboarding = z.infer<typeof onboarding>;
export interface StartUpdate {
  goal?: StartGoal | null;
  dismissed?: boolean;
  completed?: true;
}
export const readOnboarding = async () =>
  onboarding.parse(await apiClient.get<unknown>("/me/onboarding"));
export const saveOnboarding = async (data: StartUpdate) =>
  onboarding.parse(await apiClient.patch<unknown>("/me/onboarding", data));
export const prepareStarter = async (modelId: string) =>
  agent.parse(
    await apiClient.post<unknown>("/me/onboarding/starter", { model_profile_id: modelId }),
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
  data: Pick<Onboarding, "dismissed" | "completed" | "has_result" | "has_activity" | "agents">,
): boolean {
  return (
    !data.dismissed &&
    !data.completed &&
    !data.has_result &&
    !data.has_activity &&
    data.agents.length === 0
  );
}
