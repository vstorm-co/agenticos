import { Suspense } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DatasetPage from "./page";

const state = vi.hoisted(() => ({
  total: 0,
  cases: [] as unknown[],
  skips: [] as number[],
  canEdit: true,
  tab: null as string | null,
  push: vi.fn(),
  remove: vi.fn(),
}));
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push: state.push }),
  useSearchParams: () => new URLSearchParams(state.tab === null ? "" : `tab=${state.tab}`),
  usePathname: () => "/datasets/d1",
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDataset: () => ({
    dataset: {
      id: "d1",
      name: "refunds",
      description: null,
      latest_version: 3,
      case_count: 1,
      can_edit: state.canEdit,
      scoring: {},
    },
    error: null,
    update: { mutateAsync: vi.fn(), isPending: false },
    remove: { mutateAsync: state.remove, isPending: false },
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
vi.mock("@/components/datasets/grading-panel", () => ({ GradingPanel: () => <p>grading</p> }));
vi.mock("@/components/datasets/scores-panel", () => ({ ScoresPanel: () => <p>review</p> }));

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
    state.tab = null;
    state.push.mockReset();
    state.remove.mockReset();
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

  async function choose(item: string) {
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: item }));
  }

  it("offers editing the name and description to somebody who may edit it", async () => {
    await mount();
    await choose("Edit details");
    expect(screen.getByRole("dialog", { name: "Edit details" })).toBeInTheDocument();
  });

  it("offers no edit to somebody who may only read it", async () => {
    state.canEdit = false;
    await mount();
    expect(screen.queryByRole("button", { name: "Add case" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(await screen.findByRole("menuitem", { name: "Share" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Edit details" })).toBeNull();
  });

  it("shares from the menu, in a dialog", async () => {
    await mount();
    await choose("Share");
    expect(screen.getByRole("dialog", { name: "Share refunds" })).toBeInTheDocument();
  });

  it("deletes after a confirmation and goes back to the datasets", async () => {
    state.remove.mockResolvedValue(undefined);
    await mount();
    await choose("Delete");
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/datasets"));
    expect(state.remove).toHaveBeenCalled();
  });

  it("opens the tab the address names: Grading, then Review", async () => {
    state.tab = "review";
    await mount();
    expect(screen.getByText("review")).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Cases",
      "Grading",
      "Review",
    ]);
  });
});
