import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { DatasetsWidget } from "./datasets";

const useDatasetsMock = vi.fn();
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: (...args: unknown[]) => useDatasetsMock(...args),
}));

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
  beforeEach(() => vi.clearAllMocks());

  it("lists the datasets changed most recently, with size and version", () => {
    answer({ datasets: [{ id: "d1", name: "refunds", case_count: 12, latest_version: 3 }] });
    widget();
    expect(useDatasetsMock).toHaveBeenCalledWith({ sort: "updated", limit: 5 });
    expect(screen.getByRole("link", { name: /refunds/ })).toHaveAttribute("href", "/datasets/d1");
    expect(screen.getByText("12 cases · v3")).toBeInTheDocument();
  });

  it("says how many drafted cases wait on a dataset, and nothing when none do", () => {
    answer({
      datasets: [
        { id: "d1", name: "refunds", case_count: 12, latest_version: 3, pending_proposals: 4 },
        { id: "d2", name: "billing", case_count: 2, latest_version: 1, pending_proposals: 0 },
      ],
    });
    widget();
    expect(screen.getByText("4 to review")).toBeInTheDocument();
    expect(screen.queryByText("0 to review")).toBeNull();
  });

  it("says what appears here when there is nothing yet", () => {
    answer({});
    widget();
    expect(screen.getByText("No datasets yet")).toBeInTheDocument();
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
