import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { SubscriptionUsage } from "./subscription-usage";

it("does not turn unavailable usage into a full allowance", () => {
  const { rerender } = render(<SubscriptionUsage />);
  expect(screen.queryByText("Usage and limits")).not.toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  rerender(<SubscriptionUsage usage={{ status: "unavailable", observed_at: null, windows: [] }} />);
  expect(screen.queryByText("Usage and limits")).not.toBeInTheDocument();
});

it("shows provider windows, reset times and the observation timestamp", () => {
  render(
    <SubscriptionUsage
      usage={{
        status: "available",
        observed_at: "2026-11-21T22:00:00Z",
        windows: [
          {
            kind: "primary",
            remaining_percent: 39,
            duration_minutes: 10080,
            resets_at: "2026-11-22T22:00:00Z",
          },
          { kind: "five_hour", remaining_percent: 50, duration_minutes: 300, resets_at: null },
          { kind: "secondary", remaining_percent: 25, duration_minutes: 90, resets_at: null },
          { kind: "seven_day", remaining_percent: 0, duration_minutes: null, resets_at: null },
          { kind: "provider", remaining_percent: 30, duration_minutes: 1440, resets_at: null },
          { kind: "provider", remaining_percent: 20, duration_minutes: 120, resets_at: null },
        ],
      }}
    />,
  );
  expect(screen.getByText("Weekly limit")).toBeInTheDocument();
  expect(screen.getByText("39% left")).toBeInTheDocument();
  expect(screen.getByText("5-hour window")).toBeInTheDocument();
  expect(screen.getByText("90-minute window")).toBeInTheDocument();
  expect(screen.getByText("Usage window")).toBeInTheDocument();
  expect(screen.getByText(/Updated after provider responses/)).toBeInTheDocument();
  expect(screen.getByText("Daily limit")).toBeInTheDocument();
  expect(screen.getByText("2-hour window")).toBeInTheDocument();
  expect(screen.getAllByRole("progressbar")).toHaveLength(6);
});

it("labels stale observations instead of presenting them as current limits", () => {
  render(
    <SubscriptionUsage
      usage={{
        status: "stale",
        observed_at: null,
        windows: [
          { kind: "primary", remaining_percent: 30, duration_minutes: 300, resets_at: null },
        ],
      }}
    />,
  );
  expect(screen.getByText(/these values may have changed/)).toBeInTheDocument();
});
