import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowDetail } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import WorkflowEditorPage from "./page";

/**
 * The editor page's permission gate (#1787): a caller with only `workflows:view`
 * gets a read-only canvas and none of the edit chrome — no Add step, no
 * autosave/publish actions, no property panel, no conflict banner — so no
 * autosave fires to 403. A caller with `workflows:edit` gets the full editor.
 * This is the "not rendered, then 403" rule proven with an integration test, per
 * `.claude/rules/frontend.md`.
 *
 * The child components are mocked to markers so the assertions read the page's
 * composition decision directly; the real store drives the seed effect.
 */

const state = vi.hoisted(() => ({
  canEdit: true,
  status: "draft" as string,
  live: false,
  triggerActive: null as boolean | null,
  debug: null as string | null,
  clearDebug: vi.fn(),
}));
const actions = vi.hoisted(() => ({
  update: { mutate: vi.fn() },
  setActive: { mutate: vi.fn(), isPending: false },
  saveSettings: {
    mutate: vi.fn((_input: unknown, options?: { onSuccess?: () => void }) =>
      options?.onSuccess?.(),
    ),
    isPending: false,
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/workflows/w1",
  useParams: () => ({ id: "w1" }),
}));

const WORKFLOW: WorkflowDetail = {
  id: "w1",
  slug: "w",
  name: "My Workflow",
  description: null,
  status: "draft",
  visibility: "org",
  owner_user_id: null,
  current_version_id: null,
  live_trigger: null,
  tags: [],
  trigger_active: null,
  draft_revision: 3,
  created_at: null,
  updated_at: null,
  draft_graph: null,
  can_edit: true,
  settings: {
    timezone: "UTC",
    default_deadline_seconds: null,
    error_workflow_id: null,
    run_retention_days: null,
    keep_succeeded_runs: true,
    error_workflow_run_as: null,
  },
};

vi.mock("@/hooks", () => ({
  useWorkflow: () => ({
    // What the server answers: `can_edit` is this caller's reach to this
    // workflow, and false for an archived one whatever the role.
    workflow: {
      ...WORKFLOW,
      status: state.status,
      can_edit: state.canEdit && state.status !== "archived",
      current_version_id: state.live ? "v1" : null,
      trigger_active: state.triggerActive,
      tags: ["sales"],
    },
    isLoading: false,
    saveDraft: { mutateAsync: vi.fn() },
    publish: { mutateAsync: vi.fn() },
    restore: { mutateAsync: vi.fn() },
  }),
  useNodeCatalog: () => ({ nodes: [] }),
  useWorkflowActions: () => actions,
  useUrlState: () => [state.debug, state.clearDebug],
}));

vi.mock("@/components/workflows/canvas", () => ({
  WorkflowCanvas: ({ readOnly = false }: { readOnly?: boolean }) => (
    <div data-testid="canvas" data-readonly={String(readOnly)} />
  ),
  LiveRun: ({
    runId,
    onClose,
    children,
  }: {
    runId: string;
    onClose: () => void;
    children: ReactNode;
  }) => (
    <div data-testid="live-run" data-run={runId}>
      <button type="button" onClick={onClose}>
        hide
      </button>
      {children}
    </div>
  ),
}));
vi.mock("@/components/workflows/node-editor", () => ({
  NodeEditorDialog: ({ readOnly = false }: { readOnly?: boolean }) => (
    <div data-testid="node-editor" data-readonly={String(readOnly)} />
  ),
  StepDataFeed: () => <div data-testid="step-data-feed" />,
}));
vi.mock("@/components/workflows/editor", () => ({
  ConflictBanner: () => <div data-testid="conflict-banner" />,
  WorkflowSettingsForm: ({ onSave }: { onSave: (settings: unknown) => void }) => (
    <button type="button" onClick={() => onSave({ timezone: "Asia/Tokyo" })}>
      save settings
    </button>
  ),
  DebugRun: ({ runId, onDone }: { runId: string; onDone: () => void }) => (
    <button type="button" data-testid="debug-run" data-run={runId} onClick={onDone}>
      debug
    </button>
  ),
  EditorActions: () => <div data-testid="editor-actions" />,
  RunButton: ({ onStarted }: { onStarted: (runId: string) => void }) => (
    <button type="button" data-testid="run-button" onClick={() => onStarted("run-1")}>
      run
    </button>
  ),
  VersionHistory: ({ onRestore }: { onRestore?: unknown }) => (
    <div data-testid="version-history" data-restorable={String(onRestore !== undefined)} />
  ),
  useRestoreVersion: () => vi.fn(),
}));

// The page reads its route params with `use()`, so the first render suspends and
// the tree only exists after that promise settles — awaited here.
async function renderPage() {
  await act(async () => {
    render(
      <Suspense fallback={null}>
        <WorkflowEditorPage params={Promise.resolve({ id: "w1" })} />
      </Suspense>,
    );
  });
}

/** History lives in a sheet the header's button opens. */
async function openHistory() {
  await userEvent.click(await screen.findByRole("button", { name: "Versions" }));
}

beforeEach(() => {
  state.canEdit = true;
  state.status = "draft";
  state.debug = null;
  state.clearDebug.mockReset();
  state.live = false;
  state.triggerActive = null;
  vi.clearAllMocks();
});

afterEach(() => {
  useWorkflowEditorStore.getState().teardown();
});

describe("the workflow editor page permission gate", () => {
  it("gives an editor the full editor", async () => {
    state.canEdit = true;
    await renderPage();

    const canvas = await screen.findByTestId("canvas");
    expect(canvas).toHaveAttribute("data-readonly", "false");
    expect(screen.getByTestId("editor-actions")).toBeInTheDocument();
    expect(screen.getByTestId("run-button")).toBeInTheDocument();
    expect(screen.getByTestId("node-editor")).toHaveAttribute("data-readonly", "false");
    expect(screen.getByTestId("conflict-banner")).toBeInTheDocument();
    await openHistory();
    expect(screen.getByTestId("version-history")).toHaveAttribute("data-restorable", "true");
  });

  it("shows a run started from Run on the canvas until it is hidden", async () => {
    state.canEdit = true;
    await renderPage();
    await userEvent.click(await screen.findByTestId("run-button"));
    expect(screen.getByTestId("live-run")).toHaveAttribute("data-run", "run-1");
    expect(screen.getByTestId("canvas")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "hide" }));
    expect(screen.queryByTestId("live-run")).not.toBeInTheDocument();
  });

  it("gives a view-only caller a read-only editor with no edit chrome", async () => {
    state.canEdit = false;
    await renderPage();

    const canvas = await screen.findByTestId("canvas");
    expect(canvas).toHaveAttribute("data-readonly", "true");
    // No autosave/publish and no conflict banner; a step's settings open read-only.
    expect(screen.queryByTestId("editor-actions")).not.toBeInTheDocument();
    expect(screen.getByTestId("node-editor")).toHaveAttribute("data-readonly", "true");
    expect(screen.queryByTestId("conflict-banner")).not.toBeInTheDocument();
    // History stays readable, but a version cannot be restored over the draft.
    await openHistory();
    expect(screen.getByTestId("version-history")).toHaveAttribute("data-restorable", "false");
  });

  it("renders an archived workflow read-only even for a caller who could edit it", async () => {
    // The backend's `_ensure_editable` rejects every write to an archived
    // workflow, so an editor-role caller still takes the read-only path — Add step,
    // actions, autosave and publish must not mount to 403 (#1787).
    state.canEdit = true;
    state.status = "archived";
    await renderPage();

    const canvas = await screen.findByTestId("canvas");
    expect(canvas).toHaveAttribute("data-readonly", "true");
    expect(screen.queryByTestId("editor-actions")).not.toBeInTheDocument();
    expect(screen.getByTestId("node-editor")).toHaveAttribute("data-readonly", "true");
    expect(screen.queryByTestId("conflict-banner")).not.toBeInTheDocument();
    await openHistory();
    expect(screen.getByTestId("version-history")).toHaveAttribute("data-restorable", "false");
  });

  it("closes the history sheet again", async () => {
    await renderPage();
    await openHistory();
    await userEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(screen.queryByTestId("version-history")).not.toBeInTheDocument();
  });
});

describe("the workflow editor page header", () => {
  it("renames the workflow where its name stands, keeping the old one on Escape", async () => {
    await renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "My Workflow" }));
    const field = screen.getByRole("textbox", { name: "Workflow name" });
    await userEvent.clear(field);
    await userEvent.type(field, "Lead intake{Enter}");
    expect(actions.update.mutate).toHaveBeenCalledWith({
      id: "w1",
      update: { name: "Lead intake" },
    });

    await userEvent.click(screen.getByRole("button", { name: "My Workflow" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Workflow name" }), "x{Escape}");
    expect(actions.update.mutate).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "My Workflow" })).toBeInTheDocument();
  });

  it("tags the workflow and takes a tag off", async () => {
    await renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Remove tag sales" }));
    expect(actions.update.mutate).toHaveBeenCalledWith({ id: "w1", update: { tags: [] } });

    await userEvent.click(screen.getByRole("button", { name: "Tag" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Tag" }), "  Nightly {Enter}");
    expect(actions.update.mutate).toHaveBeenLastCalledWith({
      id: "w1",
      update: { tags: ["sales", "nightly"] },
    });
  });

  it("switches a live workflow's trigger from the header", async () => {
    state.live = true;
    state.triggerActive = true;
    await renderPage();

    await userEvent.click(await screen.findByRole("switch"));

    expect(actions.setActive.mutate).toHaveBeenCalledWith({ id: "w1", active: false });
  });

  it("shows a reader the trigger's state without a switch, a name they cannot edit", async () => {
    state.canEdit = false;
    state.live = true;
    state.triggerActive = false;
    await renderPage();

    expect(await screen.findByText("Paused")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "My Workflow" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove tag sales" })).not.toBeInTheDocument();
  });
});

describe("debugging a past run in the editor", () => {
  it("brings the run's data in when an editor opens it with ?debug=, and drops the request", async () => {
    state.debug = "run-9";
    await renderPage();

    const debug = screen.getByTestId("debug-run");
    expect(debug).toHaveAttribute("data-run", "run-9");
    await userEvent.click(debug);
    expect(state.clearDebug).toHaveBeenCalledWith(null);
  });

  it("does nothing for a caller who cannot edit", async () => {
    state.debug = "run-9";
    state.canEdit = false;
    await renderPage();

    expect(screen.queryByTestId("debug-run")).toBeNull();
  });
});

describe("a workflow's settings", () => {
  it("opens from the header and saves what the form hands over, then closes", async () => {
    await renderPage();

    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    await userEvent.click(screen.getByRole("button", { name: "save settings" }));

    expect(actions.saveSettings.mutate).toHaveBeenCalledWith(
      { id: "w1", settings: { timezone: "Asia/Tokyo" } },
      expect.anything(),
    );
    expect(screen.queryByRole("button", { name: "save settings" })).toBeNull();
  });
});
