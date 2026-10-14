import { Suspense } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DatasetPage from "./page";

const state = vi.hoisted(() => ({
  total: 0,
  cases: [] as unknown[],
  skips: [] as number[],
  canEdit: true,
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDataset: () => ({
    dataset: {
      id: "d1",
      name: "refunds",
      description: null,
      latest_version: 3,
      can_edit: state.canEdit,
    },
    error: null,
    update: { mutateAsync: vi.fn(), isPending: false },
  }),
  useDatasetVersions: () => ({ versions: [], isLoading: false }),
  useDatasetCases: (_id: string, { skip }: { skip: number }) => {
    state.skips.push(skip);
    return {
      cases: state.cases,
      total: state.total,
      isLoading: false,
      error: null,
      add: { mutateAsync: vi.fn() },
      update: { mutateAsync: vi.fn() },
      remove: { mutate: vi.fn() },
      importFile: { mutateAsync: vi.fn() },
      refetch: vi.fn(),
    };
  },
}));
vi.mock("@/components/sharing/sharing-panel", () => ({ SharingPanel: () => null }));
vi.mock("@/components/datasets/dataset-file-actions", () => ({ DatasetFileActions: () => null }));

const CASE = {
  id: "r1",
  case_id: "c1",
  input: "How long is the return window?",
  history: [],
  reference_answer: "30 days",
  counter_example: null,
  expected_tool_calls: [],
  order_mode: "any",
  checks: [],
  tags: [],
  note: null,
  source: "manual",
  source_run_id: null,
  source_conversation_id: null,
  source_message_id: null,
  created_by_user_id: null,
  created_at: "2026-10-13T00:00:00Z",
};

const PARAMS = Promise.resolve({ id: "d1" });

function page() {
  return (
    <Suspense fallback={null}>
      <DatasetPage params={PARAMS} />
    </Suspense>
  );
}

async function mount() {
  let rerender: (ui: ReturnType<typeof page>) => void = () => undefined;
  await act(async () => {
    rerender = render(page()).rerender;
  });
  return () => act(() => rerender(page()));
}

describe("the dataset page", () => {
  beforeEach(() => {
    state.total = 0;
    state.cases = [];
    state.skips = [];
    state.canEdit = true;
  });

  it("steps back to the last page that still exists once its cases are gone", async () => {
    state.total = 51;
    state.cases = [CASE];
    const refresh = await mount();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(state.skips.at(-1)).toBe(50);

    // The one case on the second page was removed: that page is empty, the total 50.
    state.total = 50;
    state.cases = [];
    refresh();
    expect(state.skips.at(-1)).toBe(0);
  });

  it("offers editing the name and description to somebody who may edit it", async () => {
    await mount();
    await userEvent.click(screen.getByRole("button", { name: "Edit details" }));
    expect(screen.getByRole("dialog", { name: "Edit details" })).toBeInTheDocument();
  });

  it("offers no edit to somebody who may only read it", async () => {
    state.canEdit = false;
    await mount();
    expect(screen.queryByRole("button", { name: "Edit details" })).toBeNull();
  });
});
