import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

function workflow(settings: Partial<WorkflowDetail["settings"]> = {}): WorkflowDetail {
  return {
    id: "wf",
    settings: {
      timezone: "UTC",
      default_deadline_seconds: null,
      error_workflow_id: null,
      run_retention_days: null,
      keep_succeeded_runs: true,
      error_workflow_run_as: null,
      ...settings,
    },
  } as WorkflowDetail;
}

describe("WorkflowSettingsForm", () => {
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
    });
  });

  it("opens on what is saved, and saves empty fields as unset", async () => {
    const onSave = vi.fn();
    render(
      <WorkflowSettingsForm
        workflow={workflow({
          default_deadline_seconds: 300,
          run_retention_days: 7,
          error_workflow_id: "gone",
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
    await userEvent.click(screen.getByRole("combobox", { name: "Error workflow" }));
    await userEvent.click(screen.getByRole("option", { name: "None" }));
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    expect(onSave).toHaveBeenCalledWith({
      timezone: "UTC",
      default_deadline_seconds: null,
      error_workflow_id: null,
      run_retention_days: null,
      keep_succeeded_runs: true,
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
