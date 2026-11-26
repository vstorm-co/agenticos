import { describe, expect, it } from "vitest";

import { attentionParts, evalsAttention, improveNeeded } from "./attention";
import type { AgentAttention } from "@/types/stats";

const t = (key: string, values?: Record<string, unknown>) =>
  values ? `${key}:${JSON.stringify(values)}` : key;

function attention(overrides: Partial<AgentAttention> = {}): AgentAttention {
  return {
    agent_id: "a1",
    name: "Support",
    rated_down: 0,
    failed_runs: 0,
    failing_suites: 0,
    can_edit: true,
    ...overrides,
  };
}

describe("improveNeeded", () => {
  it("holds for answers rated down or runs that failed, and for nothing else", () => {
    expect(improveNeeded(attention({ rated_down: 1 }))).toBe(true);
    expect(improveNeeded(attention({ failed_runs: 2 }))).toBe(true);
    expect(improveNeeded(attention({ failing_suites: 3 }))).toBe(false);
    expect(improveNeeded(undefined)).toBe(false);
  });
});

describe("evalsAttention", () => {
  it("lists what the agent needs attention for, a failing suite included", () => {
    const item = attention({ rated_down: 1, failing_suites: 2 });
    expect(evalsAttention(item, undefined, t)).toEqual(attentionParts(item, t));
    expect(evalsAttention(attention({ failing_suites: 1 }), undefined, t)).toHaveLength(1);
  });

  it("adds an Improve session that stopped for a person", () => {
    for (const status of ["waiting", "ready", "stopped", "failed"] as const)
      expect(evalsAttention(undefined, { status }, t)).toEqual(["improvementWaiting"]);
  });

  it("finds nothing in a session still working or in no reason at all", () => {
    for (const status of ["queued", "running"] as const)
      expect(evalsAttention(undefined, { status }, t)).toEqual([]);
    expect(evalsAttention(attention(), undefined, t)).toEqual([]);
  });
});
