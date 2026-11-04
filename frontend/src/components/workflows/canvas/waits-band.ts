import { Clock, Hourglass, type LucideIcon } from "lucide-react";

import type { Binding, NodeInstance } from "@/lib/workflows/types";

/** A step that can park the run, said on its card in words taken from its config. */
export interface WaitsBand {
  /** `person` is a human's decision, `timer` a clock or a call. */
  tone: "person" | "timer";
  icon: LucideIcon;
  /** The `workflows.waits.*` message, and what it is filled with. */
  key: "person" | "duration" | "until" | "bound" | "call" | "child" | "askWrites" | "askAll";
  values?: { count: number; unit: "days" | "hours" | "minutes" | "seconds" };
}

const UNITS = [
  ["days", 86_400],
  ["hours", 3_600],
  ["minutes", 60],
] as const;

/** `seconds` in the largest unit that holds it whole: 172800 is two days, 90 is 90 seconds. */
function duration(seconds: number): NonNullable<WaitsBand["values"]> {
  for (const [unit, size] of UNITS) {
    if (seconds % size === 0) return { count: seconds / size, unit };
  }
  return { count: seconds, unit: "seconds" };
}

/**
 * What a step says about parking the run, from its config alone - never from a
 * run, so the same card reads the same before and after one. `agent.run` has
 * none: its approvals come from the agent's own spec, which the card cannot see.
 */
export function waitsBand(instance: NodeInstance, bindings: readonly Binding[]): WaitsBand | null {
  const { config } = instance;
  switch (instance.definition_id) {
    case "human.approval":
      return { tone: "person", icon: Hourglass, key: "person" };
    case "flow.wait": {
      if (config.until_called === true) return { tone: "timer", icon: Clock, key: "call" };
      // Either field can be bound from an earlier step instead of set on the card.
      const isBound = (field: string) =>
        bindings.some(
          (binding) => binding.target_node_id === instance.id && binding.target_field === field,
        );
      if (isBound("until")) return { tone: "timer", icon: Clock, key: "until" };
      if (isBound("seconds")) return { tone: "timer", icon: Clock, key: "bound" };
      return typeof config.seconds === "number"
        ? { tone: "timer", icon: Clock, key: "duration", values: duration(config.seconds) }
        : null;
    }
    case "workflow.run":
      // `wait` is on unless the config says otherwise; off, the step goes on at once.
      return config.wait === false ? null : { tone: "timer", icon: Clock, key: "child" };
    case "mcp.call":
      // `writes` is the handler's default, so a config that never set it asks too.
      if (config.approval === "none") return null;
      return {
        tone: "person",
        icon: Hourglass,
        key: config.approval === "all" ? "askAll" : "askWrites",
      };
    default:
      return null;
  }
}
