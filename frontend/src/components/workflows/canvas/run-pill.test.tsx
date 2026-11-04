import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeRunSummary } from "./run-overlay";
import { RunPill } from "./run-pill";

const running = (startedAt: string | null): NodeRunSummary => ({
  status: "running",
  runs: 1,
  succeeded: 0,
  attempts: 1,
  problem: null,
  items: null,
  durationMs: null,
  startedAt,
});

beforeEach(() => vi.useFakeTimers({ now: Date.parse("2026-10-19T10:00:02.000Z") }));
afterEach(() => vi.useRealTimers());

describe("RunPill", () => {
  it("says a step handed its work is starting, without a timer yet", () => {
    render(<RunPill state="starting" summary={null} />);
    expect(screen.getByText("Starting")).toBeInTheDocument();
  });

  it("shows a step waiting for a person in the admin hue, with an hourglass", () => {
    const { container } = render(<RunPill state="waiting" summary={null} />);
    const pill = screen.getByText("Waiting").closest("span");
    expect(pill?.className).toContain("--domain-admin-subtle");
    expect(pill?.className).toContain("--domain-admin-line");
    expect(pill?.className).not.toContain("domain-build");
    expect(container.querySelector("svg.lucide-hourglass")).not.toBeNull();
  });

  it("counts a running step up from when the server says it started", () => {
    render(<RunPill state="running" summary={running("2026-10-19T10:00:00.500Z")} />);
    expect(screen.getByText("· 1.5 s")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText("· 2.5 s")).toBeInTheDocument();
  });

  it("reads a running step's time as a finished one's does, in minutes past one", () => {
    render(<RunPill state="running" summary={running("2026-10-19T09:47:28.000Z")} />);
    expect(screen.getByText("· 12 min 34 s")).toBeInTheDocument();
  });

  it("shows no time while this clock is behind the server's, or with no start known", () => {
    const { rerender } = render(
      <RunPill state="running" summary={running("2026-10-19T10:00:05.000Z")} />,
    );
    expect(screen.queryByText(/ s$/)).toBeNull();
    rerender(<RunPill state="running" summary={running(null)} />);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });
});
