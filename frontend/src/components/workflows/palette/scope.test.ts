import { describe, expect, it } from "vitest";

import type { NodeDefinition } from "@/lib/workflows/types";

import { MAX_SCOPE_NESTING_DEPTH, isAddableInScope, ownsAScope } from "./scope";

function def(overrides: Partial<NodeDefinition>): NodeDefinition {
  return {
    id: "http.fetch",
    version: 1,
    name: "Fetch",
    category: "Network",
    description: "",
    kind: "action",
    config_schema: null,
    input_schema: null,
    output_schema: null,
    ports: [],
    effect_kind: "pure",
    retry_guarantee: "none",
    scopes: [],
    ...overrides,
  };
}

describe("ownsAScope", () => {
  it("is true only for a control.* control node", () => {
    expect(ownsAScope(def({ id: "control.foreach", kind: "control" }))).toBe(true);
  });

  it("is false for a control node outside the control.* namespace", () => {
    expect(ownsAScope(def({ id: "logic.branch", kind: "control" }))).toBe(false);
  });

  it("is false for a control.* id that is not a control node", () => {
    expect(ownsAScope(def({ id: "control.foreach", kind: "action" }))).toBe(false);
  });

  it("is false for a plain action node", () => {
    expect(ownsAScope(def({ id: "http.fetch", kind: "action" }))).toBe(false);
  });
});

describe("isAddableInScope", () => {
  const foreach = def({ id: "control.foreach", kind: "control" });
  const action = def({ id: "http.fetch", kind: "action" });

  it("always offers a non-boundary node, at the root or inside a body", () => {
    expect(isAddableInScope(action, [])).toBe(true);
    expect(isAddableInScope(action, ["fe-1"])).toBe(true);
  });

  it("offers a boundary-shaped node at the root scope", () => {
    expect(isAddableInScope(foreach, [])).toBe(true);
  });

  it("hides a boundary-shaped node once nesting reaches the limit", () => {
    expect(isAddableInScope(foreach, ["fe-1"])).toBe(false);
  });

  it("caps foreach nesting at the outermost level", () => {
    expect(MAX_SCOPE_NESTING_DEPTH).toBe(1);
  });
});
