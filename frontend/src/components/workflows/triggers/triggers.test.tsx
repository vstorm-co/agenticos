import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  NodeDefinition,
  WorkflowDetail,
  WorkflowExposureRead,
  WorkflowExposureWithSecret,
  WorkflowGraph,
} from "@/lib/workflows/types";

import { CopyableValue } from "./copyable-value";
import { TriggerPanel } from "./trigger-panel";

const hook = {
  exposure: null as WorkflowExposureRead | null,
  isLoading: false,
  setActive: { mutate: vi.fn(), isPending: false },
  rotate: { mutate: vi.fn(), isPending: false },
};
vi.mock("@/hooks", () => ({ useWorkflowExposure: () => hook }));

function exposure(overrides: Partial<WorkflowExposureRead> = {}): WorkflowExposureRead {
  return {
    id: "e1",
    workflow_id: "wf",
    workflow_version_id: "v2",
    version_number: 2,
    node_instance_id: "n1",
    adapter: "schedule",
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

function definition(id: string, name: string): NodeDefinition {
  return { id, name, category: "triggers", version: 1 } as NodeDefinition;
}

const CATALOG = [
  definition("core.input", "Manual or API"),
  definition("trigger.chat", "Chat message"),
  definition("trigger.webhook", "Webhook"),
  definition("trigger.schedule", "Schedule"),
  definition("trigger.table_record", "New table record"),
  { id: "debug.echo", name: "Echo", category: "debug", version: 1 } as NodeDefinition,
];

function workflow(liveTrigger: string | null, published = true): WorkflowDetail {
  return {
    id: "wf",
    current_version_id: published ? "v2" : null,
    live_trigger: liveTrigger,
  } as WorkflowDetail;
}

function draftOf(definitionId: string, config: Record<string, unknown> = {}): WorkflowGraph {
  return {
    entry_node_id: "n1",
    nodes: [
      {
        id: "n1",
        definition_id: definitionId,
        definition_version: 1,
        config,
        layout: { x: 0, y: 0 },
      },
    ],
    edges: [],
    bindings: [],
    scopes: [],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  hook.exposure = null;
  hook.isLoading = false;
});

describe("TriggerPanel", () => {
  it("says a workflow never published has no live trigger yet", () => {
    render(
      <TriggerPanel
        workflow={workflow(null, false)}
        draft={draftOf("trigger.webhook")}
        catalog={CATALOG}
        canEdit
      />,
    );
    expect(screen.getByText(/Publish the workflow to switch its trigger on/)).toBeTruthy();
    expect(screen.getByText(/The draft starts from Webhook/)).toBeTruthy();
  });

  it("shows how to call a workflow that starts by hand", () => {
    render(
      <TriggerPanel
        workflow={workflow("core.input")}
        draft={draftOf("core.input")}
        catalog={CATALOG}
        canEdit
      />,
    );
    expect(screen.getByText("Manual or API")).toBeTruthy();
    expect(
      (screen.getByLabelText("Endpoint") as HTMLInputElement).value.endsWith(
        "/api/v1/workflow-runs",
      ),
    ).toBe(true);
    expect(screen.queryByText(/The draft starts from/)).toBeNull();
  });

  it("names a version that starts from no trigger, and a draft that now has one", () => {
    render(
      <TriggerPanel
        workflow={workflow(null)}
        draft={draftOf("trigger.chat")}
        catalog={CATALOG}
        canEdit
      />,
    );
    expect(screen.getByText(/No trigger - it starts by hand/)).toBeTruthy();
    expect(screen.getByText(/The draft starts from Chat message/)).toBeTruthy();
  });

  it("explains the chat's door, and a draft that has no trigger", () => {
    render(
      <TriggerPanel
        workflow={workflow("trigger.chat")}
        draft={draftOf("debug.echo")}
        catalog={CATALOG}
        canEdit={false}
      />,
    );
    expect(screen.getByText(/Members pick this workflow in the chat/)).toBeTruthy();
    expect(screen.getByText(/The draft starts from No trigger/)).toBeTruthy();
  });

  it("links a table trigger's table from the draft that has the same trigger", () => {
    const { rerender } = render(
      <TriggerPanel
        workflow={workflow("trigger.table_record")}
        draft={draftOf("trigger.table_record", { table: { table_id: "tbl", schema_version: 1 } })}
        catalog={CATALOG}
        canEdit
      />,
    );
    expect(screen.getByRole("link", { name: "Open the table" }).getAttribute("href")).toBe(
      "/tables/tbl",
    );
    rerender(
      <TriggerPanel
        workflow={workflow("trigger.table_record")}
        draft={draftOf("trigger.table_record")}
        catalog={CATALOG}
        canEdit
      />,
    );
    expect(screen.queryByRole("link", { name: "Open the table" })).toBeNull();
  });

  it("shows a live schedule's cadence and next tick, and pauses it", async () => {
    hook.exposure = exposure({ last_run_id: "r1" });
    render(
      <TriggerPanel
        workflow={workflow("trigger.schedule")}
        draft={draftOf("trigger.schedule")}
        catalog={CATALOG}
        canEdit
      />,
    );
    expect(screen.getByText("On")).toBeTruthy();
    expect(screen.getByText("Runs v2")).toBeTruthy();
    expect(screen.getByText(/^Next /)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Last run" }).getAttribute("href")).toBe(
      "/workflows/wf/runs/r1",
    );
    expect(screen.queryByRole("button", { name: "New secret" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(hook.setActive.mutate).toHaveBeenCalledWith({ id: "e1", active: false });
  });

  it("resumes a paused one, and shows it without controls to a member who cannot edit", async () => {
    hook.exposure = exposure({ is_active: false });
    const { rerender } = render(
      <TriggerPanel
        workflow={workflow("trigger.schedule")}
        draft={null}
        catalog={CATALOG}
        canEdit
      />,
    );
    expect(screen.getByText("Paused")).toBeTruthy();
    expect(screen.queryByText(/^Next /)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(hook.setActive.mutate).toHaveBeenCalledWith({ id: "e1", active: true });

    rerender(
      <TriggerPanel
        workflow={workflow("trigger.schedule")}
        draft={null}
        catalog={CATALOG}
        canEdit={false}
      />,
    );
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });

  it("shows a webhook's address and rotates its secret, revealing the new one once", async () => {
    const url = "https://agents.example.com/api/v1/workflow-webhooks/e1";
    hook.exposure = exposure({ adapter: "webhook", webhook_url: url, schedule_kind: null });
    hook.rotate.mutate.mockImplementation(
      (_id: string, options: { onSuccess: (value: WorkflowExposureWithSecret) => void }) =>
        options.onSuccess({ ...hook.exposure!, reveal_secret: "s3cret" }),
    );
    render(
      <TriggerPanel
        workflow={workflow("trigger.webhook")}
        draft={draftOf("trigger.webhook")}
        catalog={CATALOG}
        canEdit
      />,
    );
    expect(screen.getByDisplayValue(url)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "New secret" }));
    expect(hook.rotate.mutate).toHaveBeenCalledWith("e1", expect.anything());
    expect(await screen.findByRole("dialog")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("waits for the exposure, and shows nothing when the version has none", () => {
    hook.isLoading = true;
    const { container, rerender } = render(
      <TriggerPanel
        workflow={workflow("trigger.webhook")}
        draft={null}
        catalog={CATALOG}
        canEdit
      />,
    );
    expect(container.querySelector("[data-slot='skeleton'], .animate-pulse")).not.toBeNull();
    hook.isLoading = false;
    rerender(
      <TriggerPanel
        workflow={workflow("trigger.webhook")}
        draft={null}
        catalog={CATALOG}
        canEdit
      />,
    );
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });

  it("falls back to a trigger's id when the catalog does not name it", () => {
    render(<TriggerPanel workflow={workflow("trigger.gone")} draft={null} catalog={[]} canEdit />);
    expect(screen.getByText("trigger.gone")).toBeTruthy();
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
