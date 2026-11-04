import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowRead } from "@/lib/workflows/types";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

import { agentStartable, WorkflowsSection, workflowIdsOf } from "./workflows-section";

const state = vi.hoisted(() => ({
  canView: true,
  workflows: [] as Partial<WorkflowRead>[],
  isLoading: false,
  enabled: [] as boolean[],
}));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => state.canView }),
  useWorkflows: ({ enabled }: { enabled: boolean }) => {
    state.enabled.push(enabled);
    return { workflows: state.workflows, isLoading: state.isLoading };
  },
}));
vi.mock("@/components/agents/capability-settings", () => ({
  CapabilityDetail: ({ settingsExtra }: { settingsExtra: React.ReactNode }) => (
    <div>{settingsExtra}</div>
  ),
}));
vi.mock("@/components/agents/schema-form", () => ({
  SchemaForm: ({
    schema,
    onChange,
  }: {
    schema: { properties?: Record<string, unknown> };
    onChange: (config: Record<string, unknown>) => void;
  }) => (
    <button type="button" onClick={() => onChange({ wait_seconds: 30 })}>
      {`fields:${Object.keys(schema.properties ?? {}).join(",")}`}
    </button>
  ),
}));

const workflow = (overrides: Partial<WorkflowRead>): Partial<WorkflowRead> => ({
  id: "w1",
  name: "Refund",
  description: "Pays a customer back",
  status: "published",
  current_version_id: "v1",
  live_trigger: "trigger.manual",
  ...overrides,
});

const definition = {
  id: "workflows",
  config_schema: {
    type: "object",
    properties: { workflow_ids: { type: "array" }, wait_seconds: { type: "integer" } },
  },
} as unknown as CapabilityCatalogEntry;

function renderSection(config: Record<string, unknown> = {}, onChange = vi.fn()) {
  const binding = { id: "workflows", config } as CapabilityBindingSpec;
  render(<WorkflowsSection definition={definition} binding={binding} onChange={onChange} />);
  return onChange;
}

beforeEach(() => {
  state.canView = true;
  state.workflows = [];
  state.isLoading = false;
  state.enabled = [];
});

describe("agentStartable", () => {
  it("is a published, live workflow starting by hand, by the API or by a call", () => {
    const at = (overrides: Partial<WorkflowRead>) =>
      agentStartable(workflow(overrides) as WorkflowRead);
    expect(at({})).toBe(true);
    expect(at({ live_trigger: null })).toBe(true);
    expect(at({ live_trigger: "core.input" })).toBe(true);
    expect(at({ live_trigger: "trigger.workflow_call" })).toBe(true);
    expect(at({ live_trigger: "trigger.schedule" })).toBe(false);
    expect(at({ current_version_id: null })).toBe(false);
    expect(at({ status: "archived" })).toBe(false);
  });
});

describe("workflowIdsOf", () => {
  it("keeps only the ids that read as one", () => {
    expect(workflowIdsOf({ workflow_ids: ["a", 3, "b"] })).toEqual(["a", "b"]);
    expect(workflowIdsOf({})).toEqual([]);
  });
});

describe("WorkflowsSection", () => {
  it("ticks a startable workflow on and off, and keeps the rest of the config", async () => {
    state.workflows = [workflow({}), workflow({ id: "w2", name: "Report", description: null })];
    const onChange = renderSection({ workflow_ids: ["w2"], wait_seconds: 60 });

    await userEvent.click(screen.getByRole("checkbox", { name: "Let the agent start Refund" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ config: { workflow_ids: ["w2", "w1"], wait_seconds: 60 } }),
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "Let the agent start Report" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ config: { workflow_ids: [], wait_seconds: 60 } }),
    );
    expect(screen.getByText("Pays a customer back")).toBeVisible();
  });

  it("shows a workflow it cannot start, saying why, and cannot tick it", () => {
    state.workflows = [
      workflow({ id: "w3", name: "Nightly", live_trigger: "trigger.schedule" }),
      workflow({ id: "w4", name: "Draft", current_version_id: null }),
      workflow({ id: "w5", name: "Old", status: "archived" }),
    ];
    renderSection();

    expect(screen.getByRole("checkbox", { name: "Let the agent start Nightly" })).toBeDisabled();
    expect(screen.getByText(/Starts on its own trigger/)).toBeVisible();
    expect(screen.getByText("Not published yet")).toBeVisible();
    expect(screen.queryByText("Old")).toBeNull();
  });

  it("lets a workflow already given be taken away even once it cannot be started", async () => {
    state.workflows = [workflow({ id: "w3", name: "Nightly", live_trigger: "trigger.schedule" })];
    const onChange = renderSection({ workflow_ids: ["w3"] });

    await userEvent.click(screen.getByRole("checkbox", { name: "Let the agent start Nightly" }));

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ config: { workflow_ids: [] } }),
    );
  });

  it("names a workflow given that is gone, and draws the rest of the config itself", async () => {
    state.workflows = [workflow({})];
    const onChange = renderSection({ workflow_ids: ["gone"] });

    expect(screen.getByText("gone")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "fields:wait_seconds" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ config: { wait_seconds: 30, workflow_ids: ["gone"] } }),
    );
  });

  it("waits for the list, and says when there is none", () => {
    state.isLoading = true;
    const { unmount } = render(
      <WorkflowsSection
        definition={definition}
        binding={{ id: "workflows", config: {} } as CapabilityBindingSpec}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByText(/No workflow yet/)).toBeNull();
    unmount();
    state.isLoading = false;
    renderSection();
    expect(screen.getByText(/No workflow yet/)).toBeVisible();
  });

  it("asks nothing of a member who may not see workflows, and says why", () => {
    state.canView = false;
    renderSection({ workflow_ids: ["w1"] });

    expect(state.enabled).toEqual([false]);
    expect(screen.getByText(/needs workflows:view/)).toBeVisible();
    expect(screen.queryByText("w1")).toBeNull();
  });

  it("draws nothing without the capability's definition", () => {
    const { container } = render(
      <WorkflowsSection
        definition={undefined}
        binding={{ id: "workflows", config: {} } as CapabilityBindingSpec}
        onChange={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
