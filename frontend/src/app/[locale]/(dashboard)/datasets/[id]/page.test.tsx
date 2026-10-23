import { Suspense } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_SCORING } from "@/lib/scoring";
import DatasetPage from "./page";

const state = vi.hoisted(() => ({
  total: 0,
  cases: [] as unknown[],
  skips: [] as number[],
  canEdit: true,
  tab: null as string | null,
  linked: null as string | null,
  linkedCase: undefined as unknown,
  linkedError: null as Error | null,
  push: vi.fn(),
  remove: vi.fn(),
  runsView: true,
  findTwin: vi.fn(),
}));
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push: state.push }),
  useSearchParams: () =>
    new URLSearchParams({
      ...(state.tab === null ? {} : { tab: state.tab }),
      ...(state.linked === null ? {} : { case: state.linked }),
    }),
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
      pending_proposals: 0,
      scoring: DEFAULT_SCORING,
    },
    error: null,
    update: { mutateAsync: vi.fn(), isPending: false },
    remove: { mutateAsync: state.remove, isPending: false },
  }),
  useDatasetVersions: () => ({ versions: [], isLoading: false }),
  useDatasetCase: () => ({ kase: state.linkedCase, isLoading: false, error: state.linkedError }),
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
      findTwin: state.findTwin,
    };
  },
}));
vi.mock("@/components/sharing/sharing-panel", () => ({ SharingPanel: () => null }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.runsView }),
}));
vi.mock("@/components/evals/dataset-evals-panel", () => ({
  DatasetEvalsPanel: ({ datasetId }: { datasetId: string }) => <p>evals of {datasetId}</p>,
  DatasetRunEvalsButton: () => <button>run evals</button>,
}));
vi.mock("@/hooks/use-agents", () => ({ useCapabilityCatalog: () => ({ capabilities: [] }) }));
vi.mock("@/components/datasets/grading-panel", () => ({
  GradingPanel: ({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) => (
    <button type="button" onClick={() => onDirtyChange(true)}>
      grading
    </button>
  ),
}));
vi.mock("@/components/datasets/review-panel", () => ({ ReviewPanel: () => <p>review</p> }));

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
    state.runsView = true;
    state.total = 0;
    state.cases = [];
    state.skips = [];
    state.canEdit = true;
    state.tab = null;
    state.linked = null;
    state.linkedCase = undefined;
    state.linkedError = null;
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

  it("offers the first case from the empty list to somebody who may add one", async () => {
    await mount();
    await userEvent.click(screen.getAllByRole("button", { name: "Add case" }).at(-1)!);
    expect(screen.getByRole("dialog", { name: "Add case" })).toBeInTheDocument();
  });

  it("opens the case a new one would repeat in its place", async () => {
    state.findTwin.mockResolvedValue({
      id: "r9",
      case_id: "c9",
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
      created_at: "2026-10-01T00:00:00Z",
    });
    await mount();
    await userEvent.click(screen.getAllByRole("button", { name: "Add case" }).at(-1)!);
    await userEvent.type(screen.getByLabelText(/^Input/), "how long is the return window?");
    await userEvent.type(screen.getByLabelText("Reference answer"), "30 days");
    await userEvent.click(screen.getByRole("button", { name: "Save case" }));

    await userEvent.click(await screen.findByRole("button", { name: "Open it" }));

    const opened = screen.getByRole("dialog", { name: "Case" });
    expect(within(opened).getByText("How long is the return window?")).toBeInTheDocument();
    expect(within(opened).getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

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

  it("opens the case a link names, once, and edits it from there", async () => {
    state.linked = "c1";
    state.linkedCase = CASE;
    await mount();

    const dialog = screen.getByRole("dialog", { name: "Case" });
    expect(dialog).toHaveTextContent("How long is the return window?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Edit" }));
    expect(screen.getByRole("button", { name: "Save case" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says when the case a link names is gone", async () => {
    state.linked = "c9";
    state.linkedError = new Error("Not found");
    await mount();

    expect(screen.getByRole("alert")).toHaveTextContent("not in the newest version");
  });

  it("marks the Grading tab while a change there is unsaved", async () => {
    state.tab = "grading";
    await mount();
    expect(screen.queryByRole("img", { name: "Unsaved" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "grading" }));

    expect(screen.getByRole("img", { name: "Unsaved" })).toBeInTheDocument();
  });

  it("shows the dataset's eval runs, and starts one from its header", async () => {
    state.tab = "evals";
    await mount();
    expect(screen.getByText("evals of d1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "run evals" })).toBeInTheDocument();
  });

  it("shows no eval runs to who may not read runs, and leaves the start to its button", async () => {
    state.runsView = false;
    await mount();
    expect(screen.queryByRole("tab", { name: "Evals" })).toBeNull();
    // The button says why it is disabled, or hides itself; the page does not decide.
    expect(screen.getByRole("button", { name: "run evals" })).toBeInTheDocument();
  });

  it("opens on Cases when a link names Evals to who may not read runs", async () => {
    state.runsView = false;
    state.tab = "evals";
    await mount();
    expect(screen.getByRole("tab", { name: "Cases" })).toHaveAttribute("aria-selected", "true");
  });

  it("opens the tab the address names, in reading order", async () => {
    state.tab = "review";
    await mount();
    expect(screen.getByText("review")).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Cases",
      "Generated",
      "Grading",
      "Evals",
      "Review",
    ]);
  });
});
