import { describe, expect, it } from "vitest";

import { validateGraph } from "@/components/workflows/validation";
import {
  DEBUG_ECHO,
  DEBUG_RELAY,
  makeCatalog,
  testTranslator,
} from "@/components/workflows/validation/fixtures";

import { outputRefs } from "./types";
import { AUTOMATION_TEMPLATES, WORKFLOW_TEMPLATES } from "./templates";

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

  it("builds every template on the debug nodes the catalog ships", () => {
    for (const { graph } of WORKFLOW_TEMPLATES) {
      for (const node of graph.nodes) {
        expect(["debug.echo", "debug.relay"]).toContain(node.definition_id);
        expect(node.definition_version).toBe(1);
      }
    }
  });

  it("seeds a graph the publish-time rules accept, so no template starts broken", () => {
    const catalog = makeCatalog([DEBUG_ECHO, DEBUG_RELAY]);
    for (const { id, graph } of WORKFLOW_TEMPLATES) {
      expect(validateGraph(graph, catalog, testTranslator), id).toEqual([]);
    }
  });

  it("joins an echo to a relay, never two echoes", () => {
    const sequence = WORKFLOW_TEMPLATES.find((template) => template.id === "sequence");
    const kinds = sequence?.graph.nodes.map((node) => node.definition_id);
    expect(kinds).toEqual(["debug.echo", "debug.relay"]);
    expect(sequence?.graph.edges).toHaveLength(1);
    expect(sequence?.graph.bindings.map((binding) => binding.target_field)).toEqual([
      "echoed",
      "received_at",
    ]);
  });
});

describe("AUTOMATION_TEMPLATES", () => {
  it("offers the common automations, each with an id of its own", () => {
    const ids = [...WORKFLOW_TEMPLATES, ...AUTOMATION_TEMPLATES].map((template) => template.id);
    expect(AUTOMATION_TEMPLATES.map((template) => template.id)).toEqual([
      "leadIntake",
      "failureAlert",
      "dailySummary",
    ]);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("wires and binds only steps its own graph has, starting from a trigger", () => {
    for (const { graph } of AUTOMATION_TEMPLATES) {
      const nodeIds = graph.nodes.map((node) => node.id);
      expect(new Set(nodeIds).size).toBe(nodeIds.length);
      const entry = graph.nodes.find((node) => node.id === graph.entry_node_id);
      expect(entry?.definition_id.startsWith("trigger.")).toBe(true);
      for (const edge of graph.edges) {
        expect(nodeIds).toContain(edge.source_node_id);
        expect(nodeIds).toContain(edge.target_node_id);
      }
      for (const binding of graph.bindings) {
        expect(nodeIds).toContain(binding.target_node_id);
        for (const ref of outputRefs(binding.source)) expect(nodeIds).toContain(ref.node_id);
      }
    }
  });

  it("pins no resource of any deployment - those are the builder's to choose", () => {
    const text = JSON.stringify(AUTOMATION_TEMPLATES);
    for (const pin of ["agent_id", "table_id", "secret_id", "bot_id", "recipients"]) {
      expect(text).not.toContain(pin);
    }
  });
});
