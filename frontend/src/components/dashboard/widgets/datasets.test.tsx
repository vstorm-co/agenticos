import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { Perm } from "@/types/permissions";
import { DatasetsWidget } from "./datasets";

const useDatasetsMock = vi.fn();
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: (...args: unknown[]) => useDatasetsMock(...args),
}));
const granted = vi.hoisted(() => ({ perms: [] as string[] }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => granted.perms.includes(perm) }),
}));
vi.mock("@/components/datasets/create-dataset-dialog", () => ({
  CreateDatasetDialog: ({ onOpenChange }: { onOpenChange: (open: boolean) => void }) => (
    <button onClick={() => onOpenChange(false)}>create-dialog</button>
  ),
}));

const NO_STATS = {
  with_reference: 0,
  with_counter_example: 0,
  with_tool_calls: 0,
  with_checks: 0,
  by_source: { manual: 0, import: 0, conversation: 0, synthetic: 0 },
  top_tags: [],
};

const PERIOD: Period = { preset: "30d", from: "2026-09-13", to: "2026-10-13" };

function widget() {
  return render(
    <TooltipProvider>
      <DatasetsWidget title="Datasets" hint="Recent" period={PERIOD} seeAll="/datasets" />
    </TooltipProvider>,
  );
}

function answer(overrides: Record<string, unknown>) {
  useDatasetsMock.mockReturnValue({
    datasets: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  });
}

describe("DatasetsWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    granted.perms = [];
  });

  it("lists the datasets changed most recently, with size, version and what they test", () => {
    answer({
      datasets: [
        {
          id: "d1",
          name: "refunds",
          case_count: 12,
          latest_version: 3,
          stats: {
            with_reference: 5,
            with_counter_example: 1,
            with_tool_calls: 0,
            with_checks: 2,
            by_source: { manual: 2, import: 4, conversation: 6, synthetic: 0 },
            top_tags: [{ tag: "returns", cases: 7 }],
          },
        },
        { id: "d2", name: "empty", case_count: 0, latest_version: 0, stats: NO_STATS },
      ],
    });
    widget();
    expect(useDatasetsMock).toHaveBeenCalledWith({ sort: "updated", limit: 4 });
    const refunds = screen.getByRole("link", { name: /refunds/ });
    expect(refunds).toHaveAttribute("href", "/datasets/d1");
    expect(within(refunds).getByText("12 cases · v3")).toBeInTheDocument();
    expect(within(refunds).getByText("5 references")).toBeInTheDocument();
    expect(within(refunds).getByText("1 counter-example")).toBeInTheDocument();
    expect(within(refunds).getByText("2 with checks")).toBeInTheDocument();
    expect(within(refunds).queryByText(/with tool calls/)).toBeNull();
    expect(within(refunds).getByText("6 from chat · 4 imported · 2 by hand")).toBeInTheDocument();
    expect(within(refunds).getByText("#returns")).toBeInTheDocument();
    expect(within(screen.getByRole("link", { name: /empty/ })).queryByText(/from chat/)).toBeNull();
  });

  it("says how many drafted cases wait on a dataset, and nothing when none do", () => {
    answer({
      datasets: [
        {
          id: "d1",
          name: "refunds",
          case_count: 0,
          latest_version: 0,
          stats: NO_STATS,
          pending_proposals: 4,
        },
        {
          id: "d2",
          name: "billing",
          case_count: 0,
          latest_version: 0,
          stats: NO_STATS,
          pending_proposals: 0,
        },
      ],
    });
    widget();
    expect(screen.getByText("4 to review")).toBeInTheDocument();
    expect(screen.queryByText("0 to review")).toBeNull();
  });

  it("says what appears here when there is nothing yet, and offers to start one", async () => {
    granted.perms = [Perm.datasetsEdit];
    answer({});
    widget();
    expect(screen.getByText("No datasets yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New dataset" }));
    await userEvent.click(screen.getByRole("button", { name: "create-dialog" }));
    expect(screen.queryByRole("button", { name: "create-dialog" })).toBeNull();
  });

  it("offers no new dataset to somebody who may not create one", () => {
    answer({});
    widget();
    expect(screen.queryByRole("button", { name: "New dataset" })).toBeNull();
  });

  it("offers a retry when the listing failed, rather than an empty card", async () => {
    const refetch = vi.fn();
    answer({ error: new Error("502"), refetch });
    widget();
    expect(screen.queryByText("No datasets yet")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows a skeleton while loading", () => {
    answer({ isLoading: true });
    widget();
    expect(screen.queryByText("No datasets yet")).toBeNull();
  });
});
