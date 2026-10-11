import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WorkflowPicker } from "./workflow-picker";

const state = vi.hoisted(() => ({ loading: false, workflows: [] as unknown[] }));
vi.mock("@/hooks", () => ({
  useWorkflows: () => ({ workflows: state.workflows, isLoading: state.loading }),
}));

describe("WorkflowPicker", () => {
  it("offers only workflows published to be called, and picks one", async () => {
    state.workflows = [
      {
        id: "a",
        name: "Enrich a lead",
        live_trigger: "trigger.workflow_call",
        status: "published",
      },
      { id: "b", name: "Manual job", live_trigger: "trigger.manual", status: "published" },
      { id: "c", name: "Old one", live_trigger: "trigger.workflow_call", status: "archived" },
    ];
    const onChange = vi.fn();
    render(<WorkflowPicker value={null} onChange={onChange} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Workflow" }));
    expect(screen.queryByRole("option", { name: "Manual job" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Old one" })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: "Enrich a lead" }));
    expect(onChange).toHaveBeenCalledWith("a");
  });

  it("says when nothing can be called, and when the chosen one no longer can", () => {
    state.workflows = [];
    render(<WorkflowPicker label="Run" value="gone" onChange={vi.fn()} error="Refused" />);
    expect(screen.getByText(/No workflow is published/)).toBeTruthy();
    expect(screen.getByText(/can no longer be called/)).toBeTruthy();
    expect(screen.getByText("Refused")).toBeTruthy();
  });

  it("calls a choice gone that is none of those it offers", () => {
    state.workflows = [
      {
        id: "a",
        name: "Enrich a lead",
        live_trigger: "trigger.workflow_call",
        status: "published",
      },
    ];
    render(<WorkflowPicker value="b" onChange={vi.fn()} />);
    expect(screen.getByText(/can no longer be called/)).toBeTruthy();
  });

  it("waits for the list before calling a choice gone", () => {
    state.loading = true;
    render(<WorkflowPicker value="x" onChange={vi.fn()} />);
    expect(screen.queryByText(/can no longer be called/)).toBeNull();
    state.loading = false;
  });
});
