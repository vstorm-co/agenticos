import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { NodeDefinition, WorkflowGraph } from "@/lib/workflows/types";

import { READ_ONLY_INTERACTION, VersionPreview } from "./version-preview";

const DEFINITION: NodeDefinition = {
  id: "debug.echo",
  version: 1,
  name: "Echo",
  category: "debug",
  description: "",
  kind: "action",
  config_schema: null,
  input_schema: null,
  output_schema: null,
  ports: [{ id: "in", label: "In", kind: "input", schema: null }],
  effect_kind: "pure",
  retry_guarantee: "none",
  scopes: [],
};

const GRAPH: WorkflowGraph = {
  entry_node_id: "a",
  nodes: [
    {
      id: "a",
      definition_id: "debug.echo",
      definition_version: 1,
      config: {},
      layout: { x: 0, y: 0 },
    },
  ],
  edges: [],
  bindings: [],
  scopes: [],
};

describe("VersionPreview", () => {
  it("draws the frozen graph's nodes with non-interactive handles", () => {
    const { container } = render(<VersionPreview graph={GRAPH} catalog={[DEFINITION]} />);
    expect(container.querySelector('[data-node-id="a"]')).toBeTruthy();
    // Read-only still mounts the port handles so edges keep anchoring (error 008
    // otherwise), but they carry no pointer interaction and offer no connect
    // control to drag from.
    const handle = container.querySelector('[data-node-id="a"] .react-flow__handle');
    expect(handle).toBeTruthy();
    expect(handle?.className).toContain("pointer-events-none");
    expect(container.querySelector('[data-node-id="a"] button')).toBeNull();
    expect(container.querySelector("[data-version-preview]")).toBeTruthy();
  });

  it("refuses connect handlers, which a read-only preview never reaches", () => {
    const endpoint = { nodeId: "a", portId: "in" };
    expect(() => READ_ONLY_INTERACTION.beginConnect(endpoint)).toThrow();
    expect(() => READ_ONLY_INTERACTION.completeConnect(endpoint, endpoint)).toThrow();
    expect(READ_ONLY_INTERACTION.readOnly).toBe(true);
  });
});
