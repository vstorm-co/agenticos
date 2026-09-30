import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowImported } from "@/lib/workflows/types";

import { ImportWorkflowDialog } from "./import-dialog";

const push = vi.fn();
const mutate = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/hooks", () => ({
  useWorkflows: () => ({ importFile: { mutate, isPending: false } }),
}));

const IMPORTED: WorkflowImported = {
  workflow: { id: "wf-9" } as WorkflowImported["workflow"],
  unresolved: [{ node_id: "n1", step: "Run an agent", field: "agent", kind: "agent" }],
};

function answer(result: WorkflowImported) {
  mutate.mockImplementation((_file, options) => options.onSuccess(result));
}

beforeEach(() => vi.clearAllMocks());

describe("ImportWorkflowDialog", () => {
  it("imports a pasted file and lists the pins to choose, then opens the draft", async () => {
    answer(IMPORTED);
    render(<ImportWorkflowDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Or paste the file's JSON here"), {
      target: { value: '{"name": "Leads"}' },
    });
    await userEvent.click(screen.getByRole("button", { name: "Import" }));

    expect(mutate.mock.calls[0]?.[0]).toEqual({ name: "Leads" });
    expect(screen.getByText("Imported as a draft.")).toBeVisible();
    expect(screen.getByText("Run an agent")).toBeVisible();
    expect(screen.getByText("agent · agent")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Open workflow" }));
    expect(push).toHaveBeenCalledWith("/workflows/wf-9");
  });

  it("reads a chosen file, and says when there is nothing to choose", async () => {
    answer({ ...IMPORTED, unresolved: [] });
    render(<ImportWorkflowDialog open onOpenChange={vi.fn()} />);
    const file = new File(['{"name": "From disk"}'], "leads.workflow.json", {
      type: "application/json",
    });
    await userEvent.upload(screen.getByLabelText("Workflow file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Import" }));

    expect(mutate.mock.calls[0]?.[0]).toEqual({ name: "From disk" });
    expect(screen.getByText(/The file left nothing out/)).toBeVisible();
  });

  it("refuses text that is not JSON, and ignores a file dialog closed empty", async () => {
    render(<ImportWorkflowDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Workflow file"), { target: { files: [] } });
    fireEvent.change(screen.getByLabelText("Or paste the file's JSON here"), {
      target: { value: "not json" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(screen.getByText("This is not a JSON file.")).toBeVisible();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("forgets what was pasted when it is closed", async () => {
    const onOpenChange = vi.fn();
    render(<ImportWorkflowDialog open onOpenChange={onOpenChange} />);
    fireEvent.change(screen.getByLabelText("Or paste the file's JSON here"), {
      target: { value: "{}" },
    });
    await userEvent.click(screen.getAllByRole("button", { name: "Close" })[0] as HTMLElement);
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.getByLabelText("Or paste the file's JSON here")).toHaveValue("");
  });
});
