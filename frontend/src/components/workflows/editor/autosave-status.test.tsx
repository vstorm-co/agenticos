import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { echo, graph } from "@/components/workflows/validation/fixtures";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { AutosaveStatusIndicator, DraftAutosave } from "./autosave-status";
import type { AutosaveStatus } from "./use-workflow-autosave";

describe("AutosaveStatusIndicator", () => {
  it.each<[Exclude<AutosaveStatus, "idle">, string]>([
    ["pending", "Unsaved changes"],
    ["saving", "Saving…"],
    ["saved", "Saved"],
    ["conflict", "Draft changed elsewhere"],
    ["error", "Save failed — will retry"],
  ])("shows the %s copy", (status, copy) => {
    render(<AutosaveStatusIndicator status={status} />);
    expect(screen.getByRole("status")).toHaveTextContent(copy);
    expect(screen.getByRole("status")).toHaveAttribute("data-autosave-status", status);
  });

  it("renders nothing readable in the idle state", () => {
    render(<AutosaveStatusIndicator status="idle" />);
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("data-autosave-status", "idle");
    expect(region).toHaveTextContent("");
  });
});

describe("DraftAutosave", () => {
  it("drives the autosave and says how it went, saying nothing of a clean draft", () => {
    act(() => {
      const store = useWorkflowEditorStore.getState();
      store.teardown();
      store.load({ workflowId: "w1", expectedRevision: 0 });
      store.seedGraph(graph({ entry: "a", nodes: [echo("a")] }));
    });
    const saveDraft = vi.fn();
    render(<DraftAutosave saveDraft={saveDraft} />);

    expect(screen.getByRole("status")).toHaveAttribute("data-autosave-status", "idle");
    expect(saveDraft).not.toHaveBeenCalled();
  });
});
