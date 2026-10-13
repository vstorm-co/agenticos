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
    scores: [],
    total: 0,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  });
}

function score(id: string, passed: boolean | null, results: { name: string; status: string }[]) {
  return {
    id,
    dataset_id: `dataset-${id}`,
    passed,
    results: results.map((result) => ({ ...result, required: true })),
  };
}

describe("ReviewQueueWidget", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists what waits, naming the scorer that did not pass", () => {
    answer({
      total: 7,
      scores: [
        score("a", false, [
          { name: "json_schema", status: "pass" },
          { name: "tone", status: "fail" },
        ]),
        score("b", null, [{ name: "correctness", status: "skipped" }]),
        score("c", true, [{ name: "json_schema", status: "pass" }]),
      ],
    });
    widget();

    expect(useReviewQueueMock).toHaveBeenCalledWith({ limit: 5 });
    expect(screen.getByText("7 results wait for a verdict")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /tone/ })).toHaveAttribute(
      "href",
      "/datasets/dataset-a",
    );
    expect(screen.getByText("Did not pass")).toBeInTheDocument();
    expect(screen.getByText("Unscored")).toBeInTheDocument();
    expect(screen.getByText("All required scorers passed")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
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
