import { describe, expect, it } from "vitest";

import { WORKFLOW_TEMPLATES } from "./templates";

describe("WORKFLOW_TEMPLATES", () => {
  it("ships at least one starter template", () => {
    expect(WORKFLOW_TEMPLATES.length).toBeGreaterThan(0);
  });

  it("gives every template a distinct id", () => {
    const ids = WORKFLOW_TEMPLATES.map((template) => template.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("seeds a structurally valid draft graph for each template", () => {
    for (const { graph } of WORKFLOW_TEMPLATES) {
      const nodeIds = graph.nodes.map((node) => node.id);
      // The model only forbids duplicate node ids; assert it so a bad seed does
      // not reach a draft the reader then cannot open.
      expect(new Set(nodeIds).size).toBe(nodeIds.length);
      // A draft parses as a graph regardless, but a template whose entry points
      // nowhere is a broken starting point, so pin it to a real node.
      expect(nodeIds).toContain(graph.entry_node_id);
      // Every edge connects two nodes that exist in the graph.
      for (const edge of graph.edges) {
        expect(nodeIds).toContain(edge.source_node_id);
        expect(nodeIds).toContain(edge.target_node_id);
      }
    }
  });

  it("builds every template on the one node the catalog ships", () => {
    for (const { graph } of WORKFLOW_TEMPLATES) {
      for (const node of graph.nodes) {
        expect(node.definition_id).toBe("debug.echo");
        expect(node.definition_version).toBe(1);
      }
    }
  });
});
