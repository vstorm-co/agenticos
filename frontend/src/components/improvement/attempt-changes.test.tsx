import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { hunk } from "@/test-utils/authoring";
import { SESSION } from "@/test-utils/improvement";
import type { Hunk } from "@/types/authoring";
import type { Improvement } from "@/types/improvement";
import { AttemptChanges } from "./attempt-changes";

const state = vi.hoisted(() => ({
  changes: [] as Hunk[],
  isLoading: false,
  error: null as Error | null,
  select: vi.fn(),
  edit: vi.fn(),
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovementChanges: () => ({
    changes: state.changes,
    isLoading: state.isLoading,
    error: state.error,
  }),
  useImprovement: () => ({
    selectChanges: { mutateAsync: state.select, isPending: false },
    editChange: { mutateAsync: state.edit, isPending: false },
  }),
}));

function atStop(included: string[]): Improvement {
  return {
    ...SESSION,
    status: "waiting",
    stage: "filtering",
    next_step: "check",
    iterations: [{ ...SESSION.iterations[0]!, included_hunk_ids: included }],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  state.changes = [hunk({ id: "h1" }), hunk({ id: "h2", kind: "spec_field" })];
  state.isLoading = false;
  state.error = null;
  state.select.mockResolvedValue({});
  state.edit.mockResolvedValue({});
});

it("ticks which changes to test, and keeps the last one ticked", async () => {
  const view = render(<AttemptChanges session={atStop(["h1"])} editable />);
  const first = screen.getByRole("checkbox", { name: "Include change 1 in the test" });
  expect(first).toBeChecked();
  expect(first).toBeDisabled();
  expect(screen.getByText("At least one change is tested.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 2 in the test" }));
  expect(state.select).toHaveBeenLastCalledWith(["h1", "h2"]);
  view.rerender(<AttemptChanges session={atStop(["h1", "h2"])} editable />);
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 1 in the test" }));
  expect(state.select).toHaveBeenLastCalledWith(["h2"]);
});

it("rewords a change before it is tested, and only a change of the instructions", async () => {
  render(<AttemptChanges session={atStop(["h1"])} editable />);
  expect(screen.getAllByRole("button", { name: "Change the wording" })).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Change the wording" }));
  const wording = screen.getByRole("textbox", { name: "Wording of change 1" });
  expect(wording).toHaveValue("Be brief. Refunds take 30 days.");
  await userEvent.clear(wording);
  await userEvent.type(wording, "Refunds take 30 days.");
  await userEvent.click(screen.getByRole("button", { name: "Save the wording" }));
  expect(state.edit).toHaveBeenCalledWith({ hunkId: "h1", text: "Refunds take 30 days." });
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});

it("saves the proposed text as no rewording, and goes back to it", async () => {
  state.changes = [hunk({ id: "h1", edited_text: "Refunds: 30 days." })];
  render(<AttemptChanges session={atStop(["h1"])} editable />);
  expect(screen.getByText("Reworded by you")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Back to the proposed wording" }));
  expect(state.edit).toHaveBeenLastCalledWith({ hunkId: "h1", text: null });
  await userEvent.click(screen.getByRole("button", { name: "Change the wording" }));
  const wording = screen.getByRole("textbox", { name: "Wording of change 1" });
  expect(wording).toHaveValue("Refunds: 30 days.");
  await userEvent.clear(wording);
  await userEvent.type(wording, "Be brief. Refunds take 30 days.");
  await userEvent.click(screen.getByRole("button", { name: "Save the wording" }));
  expect(state.edit).toHaveBeenLastCalledWith({ hunkId: "h1", text: null });
});

it("keeps the wording open and says why when it could not be saved, and can cancel it", async () => {
  state.edit.mockRejectedValueOnce(new Error("The changes are being checked"));
  render(<AttemptChanges session={atStop(["h1"])} editable />);
  await userEvent.click(screen.getByRole("button", { name: "Change the wording" }));
  await userEvent.click(screen.getByRole("button", { name: "Save the wording" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The changes are being checked");
  expect(screen.getByRole("textbox", { name: "Wording of change 1" })).toBeInTheDocument();
  await userEvent.clear(screen.getByRole("textbox"));
  expect(screen.getByRole("button", { name: "Save the wording" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});

it("only shows the changes while they are checked", () => {
  render(<AttemptChanges session={atStop(["h1"])} editable={false} />);
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("says it is loading, why it could not read the changes, and when there are none", () => {
  state.isLoading = true;
  const view = render(<AttemptChanges session={atStop([])} editable />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading the changes…");
  state.isLoading = false;
  state.error = new Error("Changes unavailable");
  view.rerender(<AttemptChanges session={atStop([])} editable />);
  expect(screen.getByRole("alert")).toHaveTextContent("Changes unavailable");
  state.error = null;
  state.changes = [];
  view.rerender(<AttemptChanges session={{ ...atStop([]), iterations: [] }} editable />);
  expect(screen.getByText("No change was written in this attempt.")).toBeInTheDocument();
});
