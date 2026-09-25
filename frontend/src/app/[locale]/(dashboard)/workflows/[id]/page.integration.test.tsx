import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowDetail } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import WorkflowEditorPage from "./page";

/**
 * The editor page's permission gate (#1787): a caller with only `workflows:view`
 * gets a read-only canvas and none of the edit chrome — no palette, no
 * autosave/publish actions, no property panel, no conflict banner — so no
 * autosave fires to 403. A caller with `workflows:edit` gets the full editor.
 * This is the "not rendered, then 403" rule proven with an integration test, per
 * `.claude/rules/frontend.md`.
 *
 * The child components are mocked to markers so the assertions read the page's
 * composition decision directly; the real store drives the seed effect.
 */

const state = vi.hoisted(() => ({ canEdit: true, status: "draft" as string }));

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
  draft_revision: 3,
  created_at: null,
  updated_at: null,
  draft_graph: null,
};

vi.mock("@/hooks", () => ({
  usePermissions: () => ({
    can: (permission: string) => (permission === "workflows:edit" ? state.canEdit : true),
  }),
  useWorkflow: () => ({
    workflow: { ...WORKFLOW, status: state.status },
    isLoading: false,
    saveDraft: { mutateAsync: vi.fn() },
    publish: { mutateAsync: vi.fn() },
  }),
  useNodeCatalog: () => ({ nodes: [] }),
}));

vi.mock("@/components/workflows/canvas", () => ({
  WorkflowCanvas: ({ readOnly = false }: { readOnly?: boolean }) => (
    <div data-testid="canvas" data-readonly={String(readOnly)} />
  ),
}));
vi.mock("@/components/workflows/palette", () => ({
  NodePalette: () => <div data-testid="palette" />,
}));
vi.mock("@/components/workflows/property-panel", () => ({
  PropertyPanel: () => <div data-testid="property-panel" />,
}));
vi.mock("@/components/workflows/editor", () => ({
  ConflictBanner: () => <div data-testid="conflict-banner" />,
  EditorActions: () => <div data-testid="editor-actions" />,
  VersionHistory: () => <div data-testid="version-history" />,
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

beforeEach(() => {
  state.canEdit = true;
  state.status = "draft";
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
    expect(screen.getByTestId("palette")).toBeInTheDocument();
    expect(screen.getByTestId("editor-actions")).toBeInTheDocument();
    expect(screen.getByTestId("property-panel")).toBeInTheDocument();
    expect(screen.getByTestId("conflict-banner")).toBeInTheDocument();
  });

  it("gives a view-only caller a read-only editor with no edit chrome", async () => {
    state.canEdit = false;
    await renderPage();

    const canvas = await screen.findByTestId("canvas");
    expect(canvas).toHaveAttribute("data-readonly", "true");
    // No autosave/publish, no palette, no property panel, no conflict banner.
    expect(screen.queryByTestId("editor-actions")).not.toBeInTheDocument();
    expect(screen.queryByTestId("palette")).not.toBeInTheDocument();
    expect(screen.queryByTestId("property-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("conflict-banner")).not.toBeInTheDocument();
  });

  it("renders an archived workflow read-only even for a caller with workflows:edit", async () => {
    // The backend's `_ensure_editable` rejects every write to an archived
    // workflow, so an editor-role caller still takes the read-only path — palette,
    // actions, autosave and publish must not mount to 403 (#1787).
    state.canEdit = true;
    state.status = "archived";
    await renderPage();

    const canvas = await screen.findByTestId("canvas");
    expect(canvas).toHaveAttribute("data-readonly", "true");
    expect(screen.queryByTestId("editor-actions")).not.toBeInTheDocument();
    expect(screen.queryByTestId("palette")).not.toBeInTheDocument();
    expect(screen.queryByTestId("property-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("conflict-banner")).not.toBeInTheDocument();
  });
});
