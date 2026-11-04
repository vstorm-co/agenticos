import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DraftFormPreview from "./page";
const state = vi.hoisted(() => ({ canEdit: true, mutateAsync: vi.fn() }));
vi.mock("@/hooks", () => ({
  useWorkflow: () => ({
    workflow: {
      can_edit: state.canEdit,
      draft_revision: 1,
      draft_graph: {
        nodes: [
          {
            id: "form1",
            definition_id: "trigger.form",
            config: {
              title: "Project brief",
              fields: [{ name: "name", type: "text", required: true }],
            },
          },
        ],
      },
    },
  }),
  useWorkflowRuns: () => ({ start: { mutateAsync: state.mutateAsync } }),
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("entry=form1") }));
beforeEach(() => {
  state.canEdit = true;
  state.mutateAsync.mockReset().mockResolvedValue({ id: "run1" });
});
async function mount() {
  const params = Promise.resolve({ id: "workflow1" });
  await act(async () => {
    render(
      <Suspense>
        <DraftFormPreview params={params} />
      </Suspense>,
    );
  });
}
describe("Draft form preview", () => {
  it("starts the exact saved draft entry with the form's answers", async () => {
    await mount();
    await userEvent.type(screen.getByLabelText("name"), "Ada");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(state.mutateAsync).toHaveBeenCalledWith({
      workflow_id: "workflow1",
      mode: "test",
      entry_node_id: "form1",
      input: { name: "Ada" },
    });
    expect(await screen.findByRole("link", { name: "Open run" })).toHaveAttribute(
      "href",
      "/workflows/workflow1/runs/run1",
    );
  });
  it("lets readers preview without offering execution of the draft", async () => {
    state.canEdit = false;
    await mount();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
    expect(screen.getByLabelText("name")).toBeDisabled();
    expect(state.mutateAsync).not.toHaveBeenCalled();
  });
});
