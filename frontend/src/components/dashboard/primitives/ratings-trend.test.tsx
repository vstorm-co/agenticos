import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { RatingsTrend } from "./ratings-trend";

describe("the quality block", () => {
  it("counts a handful of ratings rather than drawing a trend of them", () => {
    render(
      <RatingsTrend
        positivePercent={67}
        subline="of 3 rated answers"
        data={[
          { date: "2026-10-13", likes: 1, dislikes: 1 },
          { date: "2026-10-14", likes: 1, dislikes: 0 },
        ]}
      />,
    );

    expect(screen.getByText("2 helpful")).toBeInTheDocument();
    expect(screen.getByText("1 not helpful")).toBeInTheDocument();
  });

  it("draws the trend once there are days enough to make one", () => {
    render(
      <RatingsTrend
        positivePercent={90}
        subline="of 10 rated answers"
        data={["2026-10-12", "2026-10-13", "2026-10-14"].map((date) => ({
          date,
          likes: 3,
          dislikes: 0,
        }))}
      />,
    );

    expect(screen.queryByText(/not helpful$/)).toBeNull();
  });
});
