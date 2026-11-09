import { describe, expect, it } from "vitest";

import type { NodeDefinition, NodeInstance } from "@/lib/workflows/types";

import { MAX_SCOPE_NESTING_DEPTH, isAddableInScope, ownsAScope, pasteRefusal } from "./scope";

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

  it("does not treat a split as a loop", () => {
    expect(ownsAScope(def({ id: "logic.split", kind: "control" }))).toBe(false);
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

  it("offers a trigger only at the top level, where a run begins", () => {
    const webhook = def({ id: "trigger.webhook", kind: "action", category: "triggers" });
    expect(isAddableInScope(webhook, [])).toBe(true);
    expect(isAddableInScope(webhook, ["fe-1"])).toBe(false);
  });

  it("offers a boundary-shaped node at the root scope", () => {
    expect(isAddableInScope(foreach, [])).toBe(true);
  });

  it("offers a loop inside a loop until nesting reaches the publish limit", () => {
    expect(isAddableInScope(foreach, ["fe-1", "fe-2"])).toBe(true);
    expect(isAddableInScope(foreach, ["fe-1", "fe-2", "fe-3"])).toBe(false);
  });

  it("caps nesting where publishing does", () => {
    expect(MAX_SCOPE_NESTING_DEPTH).toBe(3);
  });

  it("never offers a loop's own item and result steps: every loop already holds them", () => {
    const item = def({ id: "loop.item", kind: "control", loop_body_only: true });
    expect(isAddableInScope(item, [])).toBe(false);
    expect(isAddableInScope(item, ["fe-1"])).toBe(false);
  });

  it("never offers the debug nodes", () => {
    expect(isAddableInScope(def({ id: "debug.echo", category: "debug" }), [])).toBe(false);
  });
});

describe("pasteRefusal", () => {
  const catalog = [
    def({ id: "control.foreach", kind: "control" }),
    def({ id: "http.fetch", kind: "action" }),
    def({ id: "trigger.webhook", kind: "action", category: "triggers" }),
  ];

  function step(id: string, definitionId: string, scopeId?: string): NodeInstance {
    return {
      id,
      definition_id: definitionId,
      definition_version: 1,
      config: {},
      layout: { x: 0, y: 0 },
      ...(scopeId !== undefined ? { scope_id: scopeId } : {}),
    };
  }

  it("lets a trigger land at the top level and refuses it inside a loop", () => {
    const clip = [step("t", "trigger.webhook")];
    expect(pasteRefusal(clip, catalog, [])).toBeNull();
    expect(pasteRefusal(clip, catalog, ["fe-1"])).toBe("trigger-in-loop");
  });

  it("lets a step land anywhere", () => {
    expect(pasteRefusal([step("a", "http.fetch", "elsewhere")], catalog, ["fe-1"])).toBeNull();
  });

  it("refuses a loop exactly where the palette stops offering one", () => {
    const clip = [step("loop", "control.foreach")];
    expect(pasteRefusal(clip, catalog, ["fe-1", "fe-2"])).toBeNull();
    expect(pasteRefusal(clip, catalog, ["fe-1", "fe-2", "fe-3"])).toBe("too-deep");
  });

  it("counts the loops a copied loop carries inside it", () => {
    const clip = [
      step("outer", "control.foreach"),
      step("inner", "control.foreach", "outer"),
      step("a", "http.fetch", "inner"),
    ];
    expect(pasteRefusal(clip, catalog, ["fe-1"])).toBeNull();
    expect(pasteRefusal(clip, catalog, ["fe-1", "fe-2"])).toBe("too-deep");
  });

  it("stops counting at a loop named inside itself", () => {
    const clip = [step("a", "control.foreach", "b"), step("b", "control.foreach", "a")];
    expect(pasteRefusal(clip, catalog, [])).toBeNull();
    expect(pasteRefusal(clip, catalog, ["fe-1", "fe-2"])).toBe("too-deep");
  });

  it("leaves a step the catalog does not hold to validation", () => {
    expect(pasteRefusal([step("x", "gone.step")], catalog, ["fe-1", "fe-2", "fe-3"])).toBeNull();
  });
});
