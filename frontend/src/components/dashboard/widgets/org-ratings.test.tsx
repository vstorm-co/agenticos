import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { OrgRatingsWidget } from "./org-ratings";
import type { Period } from "@/lib/dashboard/period";

const useRatingsSummaryMock = vi.fn();
vi.mock("@/hooks", () => ({
  useRatingsSummary: (...args: unknown[]) => useRatingsSummaryMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-09-10", to: "2026-10-09" };

function withRatings(ratings: unknown) {
  useRatingsSummaryMock.mockReturnValue({
    ratings,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
}

function renderWidget() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <OrgRatingsWidget title="Answer quality" hint="" period={PERIOD} />
    </NextIntlClientProvider>,
  );
}

const SUMMARY = {
  total_ratings: 10,
  like_count: 8,
  dislike_count: 2,
  average_rating: 0.6,
  with_comments: 1,
  ratings_by_day: [{ date: "2026-10-01", likes: 8, dislikes: 2 }],
};

beforeEach(() => useRatingsSummaryMock.mockReset());

describe("the answer quality widget (#2084)", () => {
  it("splits the share of good answers by surface once there is more than one", () => {
    withRatings({
      ...SUMMARY,
      ratings_by_surface: [
        { surface: "slack", likes: 3, dislikes: 1 },
        { surface: "web", likes: 5, dislikes: 1 },
      ],
    });
    renderWidget();

    expect(screen.getByText("Slack: 75% positive")).toBeInTheDocument();
    expect(screen.getByText("Web: 83% positive")).toBeInTheDocument();
  });

  it("says nothing about surfaces when there is only one, or none reported", () => {
    withRatings({ ...SUMMARY, ratings_by_surface: [{ surface: "web", likes: 8, dislikes: 2 }] });
    const { unmount } = renderWidget();
    expect(screen.queryByText(/% positive/)).not.toBeInTheDocument();
    unmount();

    withRatings(SUMMARY);
    renderWidget();
    expect(screen.queryByText(/% positive/)).not.toBeInTheDocument();
  });

  it("shows its empty state before anything is rated", () => {
    withRatings({ ...SUMMARY, total_ratings: 0 });
    renderWidget();
    expect(screen.getByText("No ratings yet")).toBeInTheDocument();
  });
});
