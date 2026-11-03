import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Dataset } from "@/types/datasets";
import { DEFAULT_SCORING } from "@/lib/scoring";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { ReviewPolicy } from "./review-policy";
function dataset(overrides: Partial<Dataset> = {}): Dataset {
  return {
    id: "d1",
    name: "Refunds",
    description: null,
    visibility: "org",
    owner_user_id: null,
    agent_id: null,
    latest_version: 1,
    case_count: 0,
    can_edit: true,
    can_run: true,
    run_needs: [],
    pending_proposals: 0,
    scoring: DEFAULT_SCORING,
    judge_name: null,
    stats: {
      with_reference: 0,
      with_counter_example: 0,
      with_tool_calls: 0,
      with_checks: 0,
      expectation_mix: [],
      by_source: { manual: 0, import: 0, conversation: 0, synthetic: 0 },
      top_tags: [],
    },
    created_at: "2026-11-03T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

const state = vi.hoisted(() => ({ save: vi.fn() }));
vi.mock("@/hooks/use-scoring", () => ({
  useSetScoring: () => ({ mutateAsync: state.save, isPending: false }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";
beforeEach(() => {
  vi.resetAllMocks();
  useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false });
});
it("saves routing without replacing grading settings", async () => {
  const original = dataset();
  render(<ReviewPolicy dataset={original} />);
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Every result" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(state.save).toHaveBeenCalledWith({ ...original.scoring, review: { select: "all" } });
});
it("retains an unsaved selection after refusal and prevents reader edits", async () => {
  state.save.mockRejectedValue(new Error("Access changed"));
  const { rerender } = render(<ReviewPolicy dataset={dataset()} />);
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Every result" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Access changed"));
  expect(screen.getByRole("combobox")).toHaveTextContent("Every result");
  const proceed = vi.fn();
  act(() => useUnsavedChangesStore.getState().leave(proceed));
  await act(() => useUnsavedChangesStore.getState().answer("discard"));
  expect(proceed).toHaveBeenCalledOnce();
  expect(screen.getByRole("combobox")).not.toHaveTextContent("Every result");
  rerender(<ReviewPolicy key="reader" dataset={dataset({ can_edit: false })} />);
  expect(screen.getByRole("combobox")).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
});

it("takes refreshed routing unless the reader has an unsaved choice", async () => {
  const initial = dataset();
  const { rerender } = render(<ReviewPolicy dataset={initial} />);
  const updated = dataset({ scoring: { ...initial.scoring, review: { select: "all" } } });
  rerender(<ReviewPolicy dataset={updated} />);
  expect(screen.getByRole("combobox")).toHaveTextContent("Every result");
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Results that did not pass" }));
  rerender(<ReviewPolicy dataset={initial} />);
  expect(screen.getByRole("combobox")).toHaveTextContent("Results that did not pass");
  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
});
