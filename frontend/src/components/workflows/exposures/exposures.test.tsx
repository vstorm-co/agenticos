import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WorkflowDetail,
  WorkflowExposureCreated,
  WorkflowExposureRead,
} from "@/lib/workflows/types";

import { cadenceBody, cadenceDraftOf, DEFAULT_CADENCE } from "./cadence";
import { CopyableValue } from "./copyable-value";
import { ExposureDialog } from "./exposure-dialog";
import { ExposuresPanel } from "./exposures-panel";

const hook = {
  exposures: [] as WorkflowExposureRead[],
  isLoading: false,
  create: { mutate: vi.fn(), isPending: false },
  update: { mutate: vi.fn(), isPending: false },
  remove: { mutate: vi.fn(), isPending: false },
  rotate: { mutate: vi.fn(), isPending: false },
};
vi.mock("@/hooks", () => ({ useWorkflowExposures: () => hook }));

function exposure(overrides: Partial<WorkflowExposureRead> = {}): WorkflowExposureRead {
  return {
    id: "e1",
    workflow_id: "wf",
    workflow_version_id: "v2",
    version_number: 2,
    adapter: "schedule",
    name: null,
    is_active: true,
    execution_principal_user_id: "u1",
    run_input: {},
    schedule_kind: "interval",
    interval_seconds: 3600,
    cron_expression: null,
    next_fire_at: "2026-09-29T10:00:00Z",
    last_fired_at: null,
    last_run_id: null,
    webhook_url: null,
    created_at: null,
    ...overrides,
  };
}

const workflow = { id: "wf", current_version_id: "v2" } as WorkflowDetail;

beforeEach(() => {
  vi.clearAllMocks();
  hook.exposures = [];
  hook.isLoading = false;
});

describe("cadence", () => {
  it("turns each form mode into what the server schedules", () => {
    expect(cadenceBody(DEFAULT_CADENCE)).toEqual({
      schedule_kind: "interval",
      interval_seconds: 3600,
      cron_expression: null,
    });
    expect(cadenceBody({ ...DEFAULT_CADENCE, mode: "daily", time: "07:30" })).toEqual({
      schedule_kind: "cron",
      cron_expression: "30 7 * * *",
      interval_seconds: null,
    });
    expect(cadenceBody({ ...DEFAULT_CADENCE, mode: "cron", cron: " 0  9 * * 1 " })).toEqual({
      schedule_kind: "cron",
      cron_expression: "0 9 * * 1",
      interval_seconds: null,
    });
  });

  it("refuses what could not be scheduled", () => {
    expect(cadenceBody({ ...DEFAULT_CADENCE, count: "0" })).toBeNull();
    expect(cadenceBody({ ...DEFAULT_CADENCE, count: "1.5" })).toBeNull();
    expect(cadenceBody({ ...DEFAULT_CADENCE, mode: "daily", time: "7:30" })).toBeNull();
    expect(cadenceBody({ ...DEFAULT_CADENCE, mode: "daily", time: "25:00" })).toBeNull();
    expect(cadenceBody({ ...DEFAULT_CADENCE, mode: "cron", cron: "0 9 *" })).toBeNull();
  });

  it("reads a stored schedule back into the form", () => {
    expect(cadenceDraftOf(exposure({ interval_seconds: 7200 }))).toMatchObject({
      mode: "interval",
      count: "2",
      unit: "hours",
    });
    expect(cadenceDraftOf(exposure({ interval_seconds: null }))).toMatchObject({
      count: "1",
      unit: "hours",
    });
    expect(
      cadenceDraftOf(exposure({ schedule_kind: "cron", cron_expression: "5 8 * * *" })),
    ).toMatchObject({ mode: "daily", time: "08:05" });
    expect(
      cadenceDraftOf(exposure({ schedule_kind: "cron", cron_expression: "0 9 * * 1-5" })),
    ).toMatchObject({ mode: "cron", cron: "0 9 * * 1-5" });
  });
});

describe("ExposureDialog", () => {
  it("creates a webhook with only a name", async () => {
    const onSubmit = vi.fn();
    render(<ExposureDialog adapter="webhook" onOpenChange={vi.fn()} onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText("Name"), "  GitHub  ");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(onSubmit).toHaveBeenCalledWith({ adapter: "webhook", name: "GitHub" });
  });

  it("creates a schedule on each cadence, with its input", async () => {
    const onSubmit = vi.fn();
    render(<ExposureDialog adapter="schedule" onOpenChange={vi.fn()} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Every"), { target: { value: "15" } });
    await userEvent.click(screen.getByRole("combobox", { name: "Unit" }));
    await userEvent.click(screen.getByRole("option", { name: "Minutes" }));
    fireEvent.change(screen.getByLabelText("Input"), { target: { value: '{"region": "eu"}' } });
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      adapter: "schedule",
      name: null,
      run_input: { region: "eu" },
      schedule_kind: "interval",
      interval_seconds: 900,
      cron_expression: null,
    });

    await userEvent.click(screen.getByRole("combobox", { name: "Runs" }));
    await userEvent.click(screen.getByRole("option", { name: "Daily at a set time" }));
    fireEvent.change(screen.getByLabelText("Time"), { target: { value: "06:00" } });
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(onSubmit).toHaveBeenLastCalledWith(
      expect.objectContaining({ cron_expression: "0 6 * * *" }),
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Runs" }));
    await userEvent.click(screen.getByRole("option", { name: "On a cron expression" }));
    fireEvent.change(screen.getByLabelText("Cron expression"), { target: { value: "0 9" } });
    expect(screen.getByText(/Pick a cadence of at least a minute/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create" })).toHaveProperty("disabled", true);
  });

  it("will not submit an input that is not a JSON object", async () => {
    const onSubmit = vi.fn();
    render(<ExposureDialog adapter="schedule" onOpenChange={vi.fn()} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Input"), { target: { value: "[1]" } });
    expect(screen.getByRole("button", { name: "Create" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("edits a schedule it was opened on, and cancels", async () => {
    const onSubmit = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ExposureDialog
        adapter="schedule"
        exposure={exposure({ name: "Nightly", run_input: { a: 1 } })}
        onOpenChange={onOpenChange}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByText("Edit schedule")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Nightly", run_input: { a: 1 }, interval_seconds: 3600 }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("ExposuresPanel", () => {
  it("shows how to call the workflow, and why nothing is listed before a publish", () => {
    render(<ExposuresPanel workflow={{ ...workflow, current_version_id: null }} canEdit />);
    expect((screen.getByLabelText("Endpoint") as HTMLInputElement).value).toBe(
      "POST http://localhost:8000/api/v1/workflow-runs",
    );
    expect(screen.getByText(/Publish the workflow first/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "New webhook" })).toBeNull();
  });

  it("waits for the list, then says what an empty one means", () => {
    hook.isLoading = true;
    const { rerender } = render(<ExposuresPanel workflow={workflow} canEdit />);
    expect(screen.queryByText(/No webhooks or schedules yet/)).toBeNull();
    hook.isLoading = false;
    rerender(<ExposuresPanel workflow={workflow} canEdit />);
    expect(screen.getByText(/No webhooks or schedules yet/)).toBeTruthy();
  });

  it("creates a webhook and shows its secret once", async () => {
    const created: WorkflowExposureCreated = {
      ...exposure({ adapter: "webhook", webhook_url: "https://api.example/wh/e1" }),
      reveal_secret: "shh-secret",
    };
    hook.create.mutate.mockImplementation((_body, options) => options.onSuccess(created));
    render(<ExposuresPanel workflow={workflow} canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "New webhook" }));
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(hook.create.mutate).toHaveBeenCalledWith(
      { adapter: "webhook", name: null },
      expect.anything(),
    );
    const dialog = await screen.findByRole("dialog");
    expect((within(dialog).getByLabelText("Signing secret") as HTMLInputElement).value).toBe(
      "shh-secret",
    );
    expect((within(dialog).getByLabelText("Webhook URL") as HTMLInputElement).value).toBe(
      "https://api.example/wh/e1",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("closes the form and the secret without writing anything", async () => {
    hook.exposures = [exposure({ adapter: "webhook", webhook_url: "https://api.example/wh" })];
    hook.rotate.mutate.mockImplementation((_id, options) =>
      options.onSuccess({ ...hook.exposures[0], reveal_secret: "s" }),
    );
    render(<ExposuresPanel workflow={workflow} canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "New webhook" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(hook.create.mutate).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "New signing secret for Webhook" }));
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("creates a schedule without revealing anything", async () => {
    hook.create.mutate.mockImplementation((_body, options) =>
      options.onSuccess({ ...exposure(), reveal_secret: null }),
    );
    render(<ExposuresPanel workflow={workflow} canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "New schedule" }));
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("acts on each row: edit, pause, move to the live version, rotate and delete", async () => {
    hook.exposures = [
      exposure({ name: "Hourly", workflow_version_id: "v1", version_number: 1 }),
      exposure({
        id: "e2",
        adapter: "webhook",
        schedule_kind: null,
        interval_seconds: null,
        is_active: false,
        last_run_id: "r9",
        webhook_url: "https://api.example/wh/e2",
      }),
    ];
    hook.update.mutate.mockImplementation((_args, options) => options?.onSuccess?.());
    hook.rotate.mutate.mockImplementation((_id, options) =>
      options.onSuccess({ ...hook.exposures[1], reveal_secret: "new-secret" }),
    );
    render(<ExposuresPanel workflow={workflow} canEdit />);

    expect(screen.getByText("Every hour")).toBeTruthy();
    expect(screen.getByText("On a signed delivery")).toBeTruthy();
    expect(screen.getByText("Paused")).toBeTruthy();
    expect(screen.getByText(/Next /)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Last run" }).getAttribute("href")).toBe(
      "/workflows/wf/runs/r9",
    );

    await userEvent.click(screen.getByRole("button", { name: "Use the live version" }));
    expect(hook.update.mutate).toHaveBeenCalledWith({
      id: "e1",
      body: { pin_current_version: true },
    });
    await userEvent.click(screen.getByRole("button", { name: "Pause Hourly" }));
    expect(hook.update.mutate).toHaveBeenCalledWith({ id: "e1", body: { is_active: false } });
    await userEvent.click(screen.getByRole("button", { name: "Resume Webhook" }));
    expect(hook.update.mutate).toHaveBeenCalledWith({ id: "e2", body: { is_active: true } });

    await userEvent.click(screen.getByRole("button", { name: "Edit Hourly" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(hook.update.mutate).toHaveBeenLastCalledWith(
      { id: "e1", body: expect.objectContaining({ name: "Hourly", interval_seconds: 3600 }) },
      expect.anything(),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await userEvent.click(screen.getByRole("button", { name: "New signing secret for Webhook" }));
    const dialog = await screen.findByRole("dialog");
    expect((within(dialog).getByLabelText("Signing secret") as HTMLInputElement).value).toBe(
      "new-secret",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await userEvent.click(screen.getByRole("button", { name: "Delete Hourly" }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(hook.remove.mutate).toHaveBeenCalledWith("e1");
  });

  it("shows a member who cannot edit the rows without their controls", () => {
    hook.exposures = [exposure({ workflow_version_id: "v1" })];
    render(<ExposuresPanel workflow={workflow} canEdit={false} />);
    expect(screen.getByText(/A newer version is live/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Use the live version" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Pause/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "New schedule" })).toBeNull();
  });
});

describe("CopyableValue", () => {
  it("copies its value and says so", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<CopyableValue id="v" label="Endpoint" value="POST /x" />);
    await userEvent.click(screen.getByRole("button", { name: "Copy Endpoint" }));
    expect(writeText).toHaveBeenCalledWith("POST /x");
    expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
  });
});
