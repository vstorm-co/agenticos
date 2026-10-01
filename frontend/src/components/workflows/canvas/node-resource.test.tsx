import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { NodeInstance } from "@/lib/workflows/types";

import { AgentTile, ResourceLine, resourcePin } from "./node-resource";

vi.mock("@/hooks", () => ({
  useAgents: () => ({
    agents: [{ id: "a1", slug: "scorer", name: "Lead scorer", has_avatar: false }],
  }),
  useAllAgentVersions: () => ({ versions: [{ id: "v3", version: 3 }] }),
  useWorkflowTables: () => ({ tables: [{ id: "t1", name: "Leads" }] }),
  useWorkflows: () => ({ workflows: [{ id: "w1", name: "Enrich a lead" }] }),
}));

function step(config: Record<string, unknown>): NodeInstance {
  return { id: "n", definition_id: "x", definition_version: 1, config, layout: { x: 0, y: 0 } };
}

describe("resourcePin", () => {
  it("reads the agent, table or workflow a step's config pins", () => {
    expect(resourcePin(step({ agent: { agent_id: "a1", version_id: "v3" } }))).toEqual({
      kind: "agent",
      id: "a1",
      versionId: "v3",
    });
    expect(resourcePin(step({ agent: { agent_id: "a1" } }))).toMatchObject({ versionId: null });
    expect(resourcePin(step({ table: { table_id: "t1" } }))).toEqual({ kind: "table", id: "t1" });
    expect(resourcePin(step({ workflow_id: "w1" }))).toEqual({ kind: "workflow", id: "w1" });
  });

  it("finds nothing in a step that names no resource yet", () => {
    expect(resourcePin(step({}))).toBeNull();
    expect(resourcePin(step({ agent: { agent_id: "" }, table: null, workflow_id: 7 }))).toBeNull();
  });
});

describe("ResourceLine", () => {
  it("names the pinned agent with its version, or alone while no version is pinned", () => {
    const { rerender } = render(
      <ResourceLine pin={{ kind: "agent", id: "a1", versionId: "v3" }} fallback="Agents" />,
    );
    expect(screen.getByText("Lead scorer · v3")).toBeInTheDocument();
    rerender(<ResourceLine pin={{ kind: "agent", id: "a1", versionId: null }} fallback="Agents" />);
    expect(screen.getByText("Lead scorer")).toBeInTheDocument();
  });

  it("names a table or a workflow, and says what kind of step it is for one it cannot see", () => {
    const { rerender } = render(<ResourceLine pin={{ kind: "table", id: "t1" }} fallback="T" />);
    expect(screen.getByText("Leads")).toBeInTheDocument();
    rerender(<ResourceLine pin={{ kind: "workflow", id: "w1" }} fallback="W" />);
    expect(screen.getByText("Enrich a lead")).toBeInTheDocument();
    rerender(<ResourceLine pin={{ kind: "workflow", id: "gone" }} fallback="Workflows" />);
    expect(screen.getByText("Workflows")).toBeInTheDocument();
    rerender(<ResourceLine pin={{ kind: "table", id: "gone" }} fallback="Tables" />);
    expect(screen.getByText("Tables")).toBeInTheDocument();
    rerender(<ResourceLine pin={{ kind: "agent", id: "gone", versionId: null }} fallback="A" />);
    expect(screen.getByText("A")).toBeInTheDocument();
  });
});

describe("AgentTile", () => {
  it("shows the agent's face, or the step's own icon for an agent it cannot see", () => {
    const { container, rerender } = render(<AgentTile agentId="a1" fallback={<span>icon</span>} />);
    expect(container.querySelector("[data-slot=avatar], span.rounded-full")).not.toBeNull();
    expect(screen.queryByText("icon")).toBeNull();
    rerender(<AgentTile agentId="gone" fallback={<span>icon</span>} />);
    expect(screen.getByText("icon")).toBeInTheDocument();
  });
});
