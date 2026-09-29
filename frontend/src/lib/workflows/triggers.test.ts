import { describe, expect, it, vi } from "vitest";

import type { NodeDefinition, WorkflowGraph } from "@/lib/workflows/types";

import {
  isTrigger,
  sampleRunInput,
  startsByHand,
  triggerNodeOf,
  TRIGGER_CATEGORY,
} from "./triggers";

function graph(definitionId: string, config: Record<string, unknown> = {}): WorkflowGraph {
  return {
    entry_node_id: "n1",
    nodes: [
      {
        id: "n1",
        definition_id: definitionId,
        definition_version: 1,
        config,
        layout: { x: 0, y: 0 },
      },
    ],
    edges: [],
    bindings: [],
    scopes: [],
  };
}

describe("triggers", () => {
  it("tells a trigger by its category, and finds the graph's", () => {
    const trigger = { category: TRIGGER_CATEGORY } as NodeDefinition;
    expect(isTrigger(trigger)).toBe(true);
    expect(isTrigger({ category: "tables" })).toBe(false);
    expect(isTrigger(null)).toBe(false);
    const g = graph("trigger.webhook");
    expect(triggerNodeOf(g, new Map([["n1", trigger]]))?.id).toBe("n1");
    expect(triggerNodeOf(g, new Map([["n1", null]]))).toBeNull();
  });

  it("starts by hand only a version from Manual or API, or from no trigger", () => {
    expect(startsByHand(null)).toBe(true);
    expect(startsByHand("core.input")).toBe(true);
    expect(startsByHand("trigger.webhook")).toBe(false);
  });

  it("samples a test run's input in the shape the draft's trigger hands on", () => {
    vi.useFakeTimers({ now: new Date("2026-09-29T09:00:00Z") });
    expect(sampleRunInput(null)).toEqual({});
    expect(sampleRunInput(graph("core.input"))).toEqual({});
    expect(sampleRunInput(graph("trigger.chat"))).toMatchObject({ prompt: "Hello" });
    expect(sampleRunInput(graph("trigger.webhook"))).toEqual({ body: {}, delivery_id: "test" });
    expect(sampleRunInput(graph("trigger.schedule", { input: { r: "eu" } }))).toEqual({
      fired_at: "2026-09-29T09:00:00.000Z",
      input: { r: "eu" },
    });
    expect(sampleRunInput(graph("trigger.schedule")).input).toEqual({});
    expect(
      sampleRunInput(graph("trigger.table_record", { table: { table_id: "tbl" } })),
    ).toMatchObject({ table_id: "tbl", values: {}, fields: {} });
    expect(sampleRunInput(graph("trigger.table_record")).table_id).toMatch(/^0{8}-/);
    vi.useRealTimers();
  });
});
