import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WorkflowGraph,
  WorkflowVersionDetail,
  WorkflowVersionRead,
} from "@/lib/workflows/types";

import { VersionHistory } from "./version-history";

const versionsState: { current: { versions: WorkflowVersionRead[]; isLoading: boolean } } = {
  current: { versions: [], isLoading: false },
};
const detailState: {
  current: { version: WorkflowVersionDetail | undefined; isLoading: boolean; error: unknown };
} = {
  current: { version: undefined, isLoading: false, error: null },
};

vi.mock("@/hooks", () => ({
  useWorkflowVersions: () => versionsState.current,
  useWorkflowVersion: () => detailState.current,
}));

const store = vi.hoisted(() => ({ graph: null as WorkflowGraph | null }));
vi.mock("@/stores/workflow-editor-store", () => ({
  useWorkflowEditorStore: (pick: (state: typeof store) => unknown) => pick(store),
}));
vi.mock("./version-compare", () => ({
  VersionComparison: ({ draft }: { draft: WorkflowGraph }) => (
    <div data-testid="comparison">{draft.nodes.length} steps in the draft</div>
  ),
}));

vi.mock("./version-preview", () => ({
  VersionPreview: ({ graph }: { graph: WorkflowGraph }) => (
    <div data-testid="preview">{graph.entry_node_id}</div>
  ),
}));

const GRAPH: WorkflowGraph = {
  entry_node_id: "root",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

function version(over: Partial<WorkflowVersionRead>): WorkflowVersionRead {
  return {
    id: "v-id",
    version: 1,
    note: "First cut",
    published_by_user_id: null,
    budget_limit: null,
    created_at: "2024-01-15T00:00:00Z",
    ...over,
  };
}

function detail(over: Partial<WorkflowVersionDetail> = {}): WorkflowVersionDetail {
  return { ...version({ id: "a", version: 3 }), graph: GRAPH, ...over };
}

beforeEach(() => {
  versionsState.current = { versions: [], isLoading: false };
  detailState.current = { version: undefined, isLoading: false, error: null };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("VersionHistory", () => {
  it("shows nothing published yet while loading, without the empty state", () => {
    versionsState.current = { versions: [], isLoading: true };
    render(<VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} />);
    expect(screen.getByText("Version history")).toBeVisible();
    expect(screen.queryByText("No versions yet")).not.toBeInTheDocument();
  });

  it("shows the empty state once loaded with no versions", () => {
    render(<VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} />);
    expect(screen.getByText("No versions yet")).toBeVisible();
  });

  it("lists versions, and a version without a note reads as such", () => {
    versionsState.current = {
      versions: [
        version({ id: "a", version: 2, note: "Second" }),
        version({ id: "b", version: 1, note: null, created_at: null }),
      ],
      isLoading: false,
    };
    render(<VersionHistory workflowId="w1" liveVersionId="a" catalog={[]} />);
    expect(screen.getByText("Version 2")).toBeVisible();
    // The version runs start from is the one marked.
    expect(screen.getAllByText("Live")).toHaveLength(1);
    expect(screen.getByText("Second")).toBeVisible();
    expect(screen.getByText("No release note")).toBeVisible();
    expect(screen.getByText("2 versions")).toBeVisible();
  });

  it("opens a version read-only, fetching and drawing its frozen graph", async () => {
    versionsState.current = { versions: [version({ id: "a", version: 3 })], isLoading: false };
    detailState.current = { version: detail(), isLoading: false, error: null };
    render(<VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} />);

    await userEvent.click(screen.getByRole("button", { name: "View" }));

    expect(await screen.findByTestId("preview")).toHaveTextContent("root");
    expect(screen.getByRole("dialog")).toHaveTextContent("Version 3");

    // Dismissing closes the preview.
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("compares the version with the draft, and back", async () => {
    versionsState.current = { versions: [version({ id: "a", version: 3 })], isLoading: false };
    detailState.current = { version: detail(), isLoading: false, error: null };
    store.graph = {
      ...GRAPH,
      nodes: [
        { id: "n", definition_id: "x", definition_version: 1, config: {}, layout: { x: 0, y: 0 } },
      ],
    };
    render(<VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "View" }));

    await userEvent.click(await screen.findByRole("button", { name: "Compare with draft" }));
    expect(screen.getByTestId("comparison")).toHaveTextContent("1 steps in the draft");
    await userEvent.click(screen.getByRole("button", { name: "Show this version" }));
    expect(screen.getByTestId("preview")).toBeInTheDocument();
  });

  it("compares with an empty draft as one with no steps", async () => {
    versionsState.current = { versions: [version({ id: "a", version: 3 })], isLoading: false };
    detailState.current = { version: detail(), isLoading: false, error: null };
    store.graph = null;
    render(<VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "View" }));
    await userEvent.click(await screen.findByRole("button", { name: "Compare with draft" }));
    expect(screen.getByTestId("comparison")).toHaveTextContent("0 steps in the draft");
  });

  it("shows a spinner while the version graph is still loading", async () => {
    versionsState.current = { versions: [version({ id: "a", version: 3 })], isLoading: false };
    detailState.current = { version: undefined, isLoading: true, error: null };
    render(<VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} />);

    await userEvent.click(screen.getByRole("button", { name: "View" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByTestId("preview")).not.toBeInTheDocument();
    expect(screen.queryByText("This version could not be loaded.")).not.toBeInTheDocument();
  });

  it("shows an error when the version cannot be loaded", async () => {
    versionsState.current = { versions: [version({ id: "a", version: 3 })], isLoading: false };
    detailState.current = { version: undefined, isLoading: false, error: new Error("boom") };
    render(<VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} />);

    await userEvent.click(screen.getByRole("button", { name: "View" }));

    expect(await screen.findByText("This version could not be loaded.")).toBeVisible();
    expect(screen.queryByTestId("preview")).not.toBeInTheDocument();
  });

  it("offers no restore to a member who cannot edit the workflow", async () => {
    versionsState.current = { versions: [version({ id: "a", version: 3 })], isLoading: false };
    detailState.current = { version: detail(), isLoading: false, error: null };
    render(<VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} />);

    await userEvent.click(screen.getByRole("button", { name: "View" }));

    expect(screen.getByText(/Keep editing the draft/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Restore to draft" })).not.toBeInTheDocument();
  });

  it("restores only after the replacement is confirmed, then closes the preview", async () => {
    versionsState.current = { versions: [version({ id: "a", version: 3 })], isLoading: false };
    detailState.current = { version: detail(), isLoading: false, error: null };
    const onRestore = vi.fn().mockResolvedValue(true);
    render(
      <VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} onRestore={onRestore} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "View" }));
    await userEvent.click(screen.getByRole("button", { name: "Restore to draft" }));

    // The confirmation says what is lost before anything is sent.
    expect(await screen.findByText("Restore version 3 to the draft?")).toBeVisible();
    expect(screen.getByText(/unpublished changes to the draft are discarded/)).toBeVisible();
    expect(onRestore).not.toHaveBeenCalled();

    const confirm = screen.getAllByRole("button", { name: "Restore to draft" }).at(-1);
    await userEvent.click(confirm as HTMLElement);

    expect(onRestore).toHaveBeenCalledWith(expect.objectContaining({ id: "a", version: 3 }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the preview open when the restore does not land", async () => {
    versionsState.current = { versions: [version({ id: "a", version: 3 })], isLoading: false };
    detailState.current = { version: detail(), isLoading: false, error: null };
    const onRestore = vi.fn().mockResolvedValue(false);
    render(
      <VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} onRestore={onRestore} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "View" }));
    await userEvent.click(screen.getByRole("button", { name: "Restore to draft" }));
    const confirm = screen.getAllByRole("button", { name: "Restore to draft" }).at(-1);
    await userEvent.click(confirm as HTMLElement);

    await waitFor(() => expect(onRestore).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByText("Restore version 3 to the draft?")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("preview")).toBeInTheDocument();
  });

  it("does nothing when the confirmation is cancelled", async () => {
    versionsState.current = { versions: [version({ id: "a", version: 3 })], isLoading: false };
    detailState.current = { version: detail(), isLoading: false, error: null };
    const onRestore = vi.fn();
    render(
      <VersionHistory workflowId="w1" liveVersionId={null} catalog={[]} onRestore={onRestore} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "View" }));
    await userEvent.click(screen.getByRole("button", { name: "Restore to draft" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(onRestore).not.toHaveBeenCalled();
    expect(screen.getByTestId("preview")).toBeInTheDocument();
  });
});
