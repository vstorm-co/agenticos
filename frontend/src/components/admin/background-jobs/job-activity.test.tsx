import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActivityCards } from "./activity-cards";
import { ActivityFigures, KindActivityTable, formatSeconds } from "./job-activity";
import { BackgroundJobsWidget } from "@/components/dashboard/widgets/background-jobs";
import type { BackgroundJobsActivity, KindActivity } from "@/types/background-jobs";

const asked = vi.fn();
let state: { data?: BackgroundJobsActivity; error?: Error | null; isPending?: boolean } = {};

vi.mock("@/hooks/use-background-jobs", () => ({
  useBackgroundJobsActivity: (window: string) => {
    asked(window);
    return { isPending: false, error: null, refetch: vi.fn(), ...state };
  },
}));
// recharts draws nothing measurable in jsdom; the series and the data are the contract.
vi.mock("@/components/dashboard/primitives/stacked-bars", () => ({
  StackedBars: ({ data, series }: { data: unknown[]; series: { label: string }[] }) => (
    <div data-testid="chart" data-points={data.length}>
      {series.map((one) => one.label).join(",")}
    </div>
  ),
}));

function kind(overrides: Partial<KindActivity>): KindActivity {
  return {
    kind: "ingest-document",
    pool: "ingest",
    finished: 10,
    dead: 0,
    run_p50_seconds: 2,
    run_p95_seconds: 9,
    wait_p95_seconds: 0.4,
    ...overrides,
  };
}

function activity(overrides: Partial<BackgroundJobsActivity> = {}): BackgroundJobsActivity {
  return {
    window: "day",
    bucket_seconds: 3600,
    buckets: [
      { start: "2026-10-20T10:00:00Z", succeeded: 30, dead: 2, cancelled: 1 },
      { start: "2026-10-20T11:00:00Z", succeeded: 7, dead: 0, cancelled: 0 },
    ],
    kinds: [kind({}), kind({ kind: "sweep", pool: "system", finished: 30, dead: 2 })],
    oldest_wait_seconds: 125,
    ...overrides,
  };
}

beforeEach(() => {
  asked.mockReset();
  state = { data: activity() };
});

describe("formatSeconds", () => {
  it("reads in the unit the figure is in", () => {
    expect(formatSeconds(null)).toBe("—");
    expect(formatSeconds(0.25)).toBe("250 ms");
    expect(formatSeconds(12)).toBe("12 s");
    expect(formatSeconds(150)).toBe("2.5 min");
    expect(formatSeconds(5400)).toBe("1.5 h");
  });
});

describe("the activity figures", () => {
  it("adds up the window and names the dead share", () => {
    render(<ActivityFigures activity={activity()} />);

    expect(screen.getByText("40")).toBeInTheDocument();
    expect(screen.getByText("about 20 an hour")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("5% of finished")).toBeInTheDocument();
    expect(screen.getByText("2.1 min")).toBeInTheDocument();
    // The slowest pickup is the kind whose due jobs waited longest.
    expect(screen.getByText("400 ms")).toBeInTheDocument();
  });

  it("says none died, and that nothing waits", () => {
    const quiet = activity({
      buckets: [{ start: "2026-10-20T10:00:00Z", succeeded: 3, dead: 0, cancelled: 0 }],
      oldest_wait_seconds: null,
    });
    render(<ActivityFigures activity={quiet} />);

    expect(screen.getByText("none")).toBeInTheDocument();
    expect(screen.getByText("nothing due is waiting")).toBeInTheDocument();
  });
});

describe("the kinds table", () => {
  it("lists each kind with its volume, deaths and timings", () => {
    render(<KindActivityTable kinds={activity().kinds} />);

    const row = screen.getByText("sweep").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("30")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("2")).toHaveClass("text-destructive");
  });

  it("says when nothing finished", () => {
    render(<KindActivityTable kinds={[]} />);

    expect(screen.getByText("Nothing finished in this window.")).toBeInTheDocument();
  });
});

describe("the activity cards", () => {
  it("charts the day, and asks for the week when it is chosen", async () => {
    render(<ActivityCards />);

    expect(asked).toHaveBeenLastCalledWith("day");
    expect(screen.getByTestId("chart")).toHaveAttribute("data-points", "2");
    expect(screen.getByTestId("chart")).toHaveTextContent("Succeeded,Dead,Cancelled");

    await userEvent.click(screen.getByRole("button", { name: "7 days" }));

    expect(asked).toHaveBeenLastCalledWith("week");
  });

  it("says when the activity could not be read", () => {
    state = { error: new Error("down") };
    render(<ActivityCards />);

    expect(screen.getByText("The activity could not be read.")).toBeInTheDocument();
  });
});

describe("the deployment card", () => {
  const props = { title: "Background jobs", hint: "", period: "30d" as never };

  it("draws the day's figures and chart", () => {
    render(<BackgroundJobsWidget {...props} />);

    expect(asked).toHaveBeenCalledWith("day");
    expect(screen.getByTestId("chart")).toBeInTheDocument();
  });

  it("says a quiet day is quiet rather than drawing empty columns", () => {
    state = {
      data: activity({
        buckets: [{ start: "2026-10-20T10:00:00Z", succeeded: 0, dead: 0, cancelled: 0 }],
      }),
    };
    render(<BackgroundJobsWidget {...props} />);

    expect(screen.getByText("Nothing finished yet")).toBeInTheDocument();
    expect(screen.queryByTestId("chart")).toBeNull();
  });
});
