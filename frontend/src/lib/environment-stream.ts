import { z } from "zod";

import {
  conversationEnvironment,
  type ConversationEnvironment,
} from "./conversation-environments-api";

const text = z.string().nullable().optional();
const frame = z.object({
  kind: z.enum([
    "browser_opened",
    "browser_step",
    "browser_frame",
    "browser_finished",
    "browser_held",
    "browser_released",
    "browser_needs_person",
    "browser_pointer",
    "browser_control_error",
  ]),
  call_id: z.string(),
  step: z.number().int().nonnegative(),
  url: text,
  title: text,
  tab_id: text,
  native_id: text,
  resumable: z.boolean().optional(),
  navigable: z.boolean().optional(),
  max_steps: z.number().int().nullable().optional(),
  goal: text,
  operation: text,
  target: text,
  reason: text,
  run_id: text,
  by: text,
  by_user_id: text,
  x: z.number().nullable().optional(),
  y: z.number().nullable().optional(),
  image: z
    .string()
    .refine(
      (value) =>
        value.startsWith("data:image/jpeg;base64,") || value.startsWith("data:image/png;base64,"),
    )
    .nullable()
    .optional(),
  outcome: z.enum(["done", "blocked", "exhausted", "failed"]).nullable().optional(),
  detail: text,
});

const event = z.discriminatedUnion("type", [
  z.object({ type: z.literal("environment_state"), data: conversationEnvironment }),
  z.object({ type: z.literal("browser_event"), data: frame }),
]);

export type EnvironmentStreamEvent = z.infer<typeof event>;

/** An invalid or differently scoped event must not update the current environment. */
export function parseEnvironmentEvent(
  value: unknown,
  expected: Pick<ConversationEnvironment, "id" | "agent_id" | "kind" | "execution_target">,
): EnvironmentStreamEvent | null {
  const parsed = event.safeParse(value);
  if (!parsed.success) return null;
  if (parsed.data.type === "browser_event")
    return parsed.data.data.call_id === expected.id ? parsed.data : null;
  const actual = parsed.data.data;
  return actual.id === expected.id &&
    actual.agent_id === expected.agent_id &&
    actual.kind === expected.kind &&
    actual.execution_target === expected.execution_target
    ? parsed.data
    : null;
}
