import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEBUG_ECHO, echo, graph } from "@/components/workflows/validation/fixtures";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import type { WorkflowDetail } from "@/lib/workflows/types";

import { EditorActions } from "./editor-actions";

vi.mock("@/hooks", () => ({
  useWorkflowVersion: () => ({ version: undefined }),
  useWorkflowVersions: () => ({ versions: [], isLoading: false }),
}));

const WORKFLOW = { id: "w1", status: "draft", current_version_id: null } as WorkflowDetail;

beforeEach(() => {
  act(() => {
    const store = useWorkflowEditorStore.getState();
    store.teardown();
    store.load({ workflowId: "w1", expectedRevision: 0 });
    store.seedGraph(graph({ entry: "a", nodes: [echo("a")] }));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("EditorActions", () => {
  it("renders the save status and the publish control, and drives autosave", () => {
    const saveDraft = vi.fn();
    render(
      <EditorActions
        workflow={WORKFLOW}
        catalog={[DEBUG_ECHO]}
        saveDraft={saveDraft}
        publish={vi.fn()}
      />,
    );

    // A freshly loaded, clean draft shows no save chatter and offers publish.
    expect(screen.getByRole("status")).toHaveAttribute("data-autosave-status", "idle");
    expect(screen.getByRole("button", { name: /Publish/ })).toBeVisible();
    expect(saveDraft).not.toHaveBeenCalled();
  });
});
