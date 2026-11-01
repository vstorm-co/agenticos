import { fireEvent, render as renderRaw, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ReactNode } from "react";
import type { WorkflowDetail } from "@/lib/workflows/types";

import { WorkflowSettingsForm } from "./settings-form";

vi.mock("@/hooks", () => ({
  useWorkflows: () => ({
    workflows: [
      { id: "wf", name: "Leads", live_trigger: "trigger.manual" },
      { id: "h1", name: "Tell the team", live_trigger: "trigger.workflow_failed" },
      { id: "h2", name: "Page on-call", live_trigger: "trigger.manual" },
    ],
  }),
}));

function render(ui: ReactNode) {
  const result = renderRaw(ui);
  for (const name of ["Timing and error handling", "Run history and retention", "Limits"]) {
    const toggle = screen.getByRole("button", { name });
    if (toggle.getAttribute("aria-expanded") === "false") fireEvent.click(toggle);
  }
  return result;
}

function workflow(settings: Partial<WorkflowDetail["settings"]> = {}): WorkflowDetail {
  return {
    id: "wf",
    settings: {
      timezone: "UTC",
      default_deadline_seconds: null,
      error_workflow_id: null,
      run_retention_days: null,
      keep_succeeded_runs: true,
      max_concurrent_runs: null,
      run_budget_usd: null,
      monthly_budget_usd: null,
      error_workflow_run_as: null,
      ...settings,
    },
  } as WorkflowDetail;
}

describe("WorkflowSettingsForm", () => {
  it("keeps default settings short, and opens any limits already configured", () => {
    const { unmount } = renderRaw(
      <WorkflowSettingsForm
        workflow={workflow()}
        disabled={false}
        saving={false}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Timezone")).toBeVisible();
    expect(screen.queryByLabelText("Runs under way at once")).toBeNull();
    unmount();
    renderRaw(
      <WorkflowSettingsForm
        workflow={workflow({ max_concurrent_runs: 3 })}
        disabled={false}
        saving={false}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Runs under way at once")).toHaveValue(3);
  });

  it("saves what was set, in the units the service takes", async () => {
    const onSave = vi.fn();
    render(
      <WorkflowSettingsForm
        workflow={workflow()}
        disabled={false}
        saving={false}
        onSave={onSave}
      />,
    );

    fireEvent.change(screen.getByLabelText("Timezone"), { target: { value: "Europe/Warsaw" } });
    fireEvent.change(screen.getByLabelText("Default deadline (minutes)"), {
      target: { value: "10" },
    });
    fireEvent.change(screen.getByLabelText("Keep runs for (days)"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("Runs under way at once"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Most one run may spend (USD)"), {
      target: { value: "0.5" },
    });
    fireEvent.change(screen.getByLabelText("Most its runs may spend a month (USD)"), {
      target: { value: "25" },
    });
    await userEvent.click(screen.getByRole("switch", { name: "Keep runs that succeeded" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Error workflow" }));
    expect(screen.queryByRole("option", { name: "Page on-call" })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: "Tell the team" }));
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    expect(onSave).toHaveBeenCalledWith({
      timezone: "Europe/Warsaw",
      default_deadline_seconds: 600,
      error_workflow_id: "h1",
      run_retention_days: 30,
      keep_succeeded_runs: false,
      max_concurrent_runs: 3,
      run_budget_usd: 0.5,
      monthly_budget_usd: 25,
    });
  });

  it("preserves exponent notation and a saved sub-minute deadline", async () => {
    const onSave = vi.fn();
    render(
      <WorkflowSettingsForm
        workflow={workflow({ default_deadline_seconds: 30 })}
        disabled={false}
        saving={false}
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByLabelText("Runs under way at once"), { target: { value: "1e2" } });
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ max_concurrent_runs: 100, default_deadline_seconds: 30 }),
    );
  });

  it.each([
    ["Runs under way at once", "1.5"],
    ["Runs under way at once", "0"],
    ["Runs under way at once", "1001"],
    ["Keep runs for (days)", "3651"],
    ["Most one run may spend (USD)", "-1"],
  ])("refuses invalid %s instead of changing its meaning", async (label, value) => {
    const onSave = vi.fn();
    render(
      <WorkflowSettingsForm
        workflow={workflow()}
        disabled={false}
        saving={false}
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByLabelText(label)).toBeInvalid();
  });

  it("submits from a field with Enter", async () => {
    const onSave = vi.fn();
    render(
      <WorkflowSettingsForm
        workflow={workflow()}
        disabled={false}
        saving={false}
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByLabelText("Runs under way at once"));
    await userEvent.keyboard("2{Enter}");
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ max_concurrent_runs: 2 }));
  });

  it("opens on what is saved, and saves empty fields as unset", async () => {
    const onSave = vi.fn();
    render(
      <WorkflowSettingsForm
        workflow={workflow({
          default_deadline_seconds: 300,
          run_retention_days: 7,
          error_workflow_id: "gone",
          max_concurrent_runs: 2,
          run_budget_usd: 1,
          monthly_budget_usd: 40,
        })}
        disabled={false}
        saving={false}
        onSave={onSave}
      />,
    );
    expect(screen.getByLabelText("Default deadline (minutes)")).toHaveValue(5);
    expect(screen.getByRole("combobox", { name: "Error workflow" })).toHaveTextContent(
      "A workflow that can no longer be picked",
    );

    fireEvent.change(screen.getByLabelText("Timezone"), { target: { value: " " } });
    fireEvent.change(screen.getByLabelText("Default deadline (minutes)"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("Keep runs for (days)"), { target: { value: "" } });
    expect(screen.getByLabelText("Most its runs may spend a month (USD)")).toHaveValue(40);
    for (const label of [
      "Runs under way at once",
      "Most one run may spend (USD)",
      "Most its runs may spend a month (USD)",
    ]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: "" } });
    }
    await userEvent.click(screen.getByRole("combobox", { name: "Error workflow" }));
    await userEvent.click(screen.getByRole("option", { name: "None" }));
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    expect(onSave).toHaveBeenCalledWith({
      timezone: "UTC",
      default_deadline_seconds: null,
      error_workflow_id: null,
      run_retention_days: null,
      keep_succeeded_runs: true,
      max_concurrent_runs: null,
      run_budget_usd: null,
      monthly_budget_usd: null,
    });
  });

  it("says what time it is in the zone, and refuses one the browser does not know", async () => {
    const onSave = vi.fn();
    render(
      <WorkflowSettingsForm
        workflow={workflow()}
        disabled={false}
        saving={false}
        onSave={onSave}
      />,
    );
    expect(screen.getByText(/^It is \d{1,2}:\d{2}( [AP]M)? there now\./)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Timezone"), { target: { value: "Mars/Olympus" } });
    expect(screen.getByText("Mars/Olympus is not a timezone this browser knows.")).toBeTruthy();
    expect(screen.getByLabelText("Timezone")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();
  });

  it("does not take any other failure for an unknown zone", () => {
    const format = vi.spyOn(Intl, "DateTimeFormat").mockImplementation(() => {
      throw new TypeError("broken");
    });
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() =>
      render(
        <WorkflowSettingsForm
          workflow={workflow()}
          disabled={false}
          saving={false}
          onSave={vi.fn()}
        />,
      ),
    ).toThrow("broken");
    format.mockRestore();
    vi.mocked(console.error).mockRestore();
  });

  it("reads without writing for a caller who cannot edit", () => {
    render(<WorkflowSettingsForm workflow={workflow()} disabled saving={false} onSave={vi.fn()} />);
    expect(screen.getByLabelText("Timezone")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save settings" })).toBeNull();
  });
});
