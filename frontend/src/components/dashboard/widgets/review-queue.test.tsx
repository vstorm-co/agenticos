import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { ReviewQueueWidget } from "./review-queue";

const useReviewQueueMock = vi.fn();
vi.mock("@/hooks/use-scoring", () => ({
  useReviewQueue: (...args: unknown[]) => useReviewQueueMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-09-13", to: "2026-10-13" };

function widget() {
  return render(
    <TooltipProvider>
      <ReviewQueueWidget title="Awaiting review" hint="Queue" period={PERIOD} seeAll="/datasets" />
    </TooltipProvider>,
  );
}

function answer(overrides: Record<string, unknown>) {
  useReviewQueueMock.mockReturnValue({
    datasets: [],
    total: 0,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  });
}

function pending(id: string, failed: number, unscored: number, passed: number) {
  return { dataset_id: id, name: `Dataset ${id}`, failed, unscored, passed };
}

describe("ReviewQueueWidget", () => {
  beforeEach(() => vi.clearAllMocks());

  it("breaks what waits down by outcome and by dataset, each opening on its scores", () => {
    answer({ total: 7, datasets: [pending("a", 3, 1, 0), pending("b", 1, 0, 2)] });
    widget();

    expect(useReviewQueueMock).toHaveBeenCalledWith({ limit: 1 });
    expect(screen.getByText("7 results wait for a verdict")).toBeInTheDocument();
    expect(screen.getByText("4 did not pass")).toBeInTheDocument();
    expect(screen.getAllByText("1 unscored")).toHaveLength(2);
    expect(screen.getAllByText("2 passed")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Dataset a/ })).toHaveAttribute(
      "href",
      "/datasets/a?tab=review",
    );
    expect(screen.getByRole("link", { name: /Dataset b/ })).toHaveTextContent(
      "1 did not pass2 passed",
    );
  });

  it("says what appears here when nothing waits", () => {
    answer({});
    widget();
    expect(screen.getByText("Nothing to review")).toBeInTheDocument();
  });

  it("offers a retry when the queue could not be read", async () => {
    const refetch = vi.fn();
    answer({ error: new Error("502"), refetch });
    widget();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows a skeleton while loading", () => {
    answer({ isLoading: true });
    widget();
    expect(screen.queryByText("Nothing to review")).toBeNull();
  });
});
