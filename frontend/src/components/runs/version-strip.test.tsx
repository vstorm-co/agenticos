import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VersionStrip } from "./version-strip";
import { useAgent, useVersionUsage } from "@/hooks";
import type { VersionUsageRow } from "@/types/stats";

vi.mock("@/hooks", () => ({
  useVersionUsage: vi.fn(),
  useAgent: vi.fn(),
}));

const refetch = vi.fn();

function row(over: Partial<VersionUsageRow> = {}): VersionUsageRow {
  return {
    agent_version_id: "version-1",
    version: 1,
    runs: 4,
    completed_runs: 4,
    p95_ms: 900,
    avg_cost_usd: "0.01",
    like_count: 0,
    rating_count: 0,
    ...over,
  };
}

function mockVersions(over: Partial<ReturnType<typeof useVersionUsage>> = {}) {
  vi.mocked(useVersionUsage).mockReturnValue({
    byVersion: [],
    isLoading: false,
    error: null,
    refetch,
    ...over,
  } as ReturnType<typeof useVersionUsage>);
}

function mockAgent(currentVersionId: string | null) {
  vi.mocked(useAgent).mockReturnValue({
    agent: currentVersionId === null ? undefined : { current_version_id: currentVersionId },
  } as ReturnType<typeof useAgent>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockAgent(null);
});

describe("VersionStrip", () => {
  it("keeps the card's title and caption over a skeleton while loading", () => {
    mockVersions({ isLoading: true });
    const { container } = render(<VersionStrip agentId="a1" />);
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    // The shell stays put as the summary resolves, so the block does not jump shape.
    expect(screen.getByText("By version")).toBeInTheDocument();
  });

  it("says the summary could not be read inside the card, and retries", async () => {
    mockVersions({ error: new Error("boom") });
    render(<VersionStrip agentId="a1" />);
    expect(screen.getByText("By version")).toBeInTheDocument();
    expect(screen.getByText("The per-version summary could not be read")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("renders nothing when no version ran in the window", () => {
    mockVersions({ byVersion: [] });
    const { container } = render(<VersionStrip agentId="a1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one card per version, with its runs, share, cost and latency", () => {
    mockVersions({
      byVersion: [
        row({ agent_version_id: "v2", version: 2, runs: 4, completed_runs: 4 }),
        row({
          agent_version_id: "v3",
          version: 3,
          runs: 3,
          completed_runs: 1,
          p95_ms: 1400,
          avg_cost_usd: "0.02",
        }),
      ],
    });
    mockAgent("v3");
    render(<VersionStrip agentId="a1" />);

    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getByText("3 runs")).toBeInTheDocument();
    expect(screen.getByText("4 runs")).toBeInTheDocument();
    // Completed share, nothing excluded: v2 is 4/4, v3 is 1/3.
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText("33%")).toBeInTheDocument();
    expect(screen.getByText("$0.02")).toBeInTheDocument();
    expect(screen.getByText("1.4 s")).toBeInTheDocument();
  });

  it("marks the agent's current version and only that one", () => {
    mockVersions({
      byVersion: [
        row({ agent_version_id: "v2", version: 2 }),
        row({ agent_version_id: "v3", version: 3 }),
      ],
    });
    mockAgent("v3");
    render(<VersionStrip agentId="a1" />);

    const current = screen.getByText("Current");
    expect(within(screen.getByText("v3").parentElement!).getByText("Current")).toBe(current);
    expect(within(screen.getByText("v2").parentElement!).queryByText("Current")).toBeNull();
  });

  it("marks nothing when the current version is unknown", () => {
    mockVersions({ byVersion: [row({ agent_version_id: "v2", version: 2 })] });
    mockAgent(null);
    render(<VersionStrip agentId="a1" />);
    expect(screen.queryByText("Current")).toBeNull();
  });

  it("names a deleted version and dashes its missing cost and latency", () => {
    mockVersions({
      byVersion: [
        row({
          agent_version_id: null,
          version: null,
          runs: 2,
          completed_runs: 0,
          p95_ms: null,
          avg_cost_usd: null,
        }),
      ],
    });
    render(<VersionStrip agentId="a1" />);

    expect(screen.getByText("Deleted version")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
    // Cost and p95 both absent - two dashes, not a fabricated zero.
    expect(screen.getAllByText("—")).toHaveLength(2);
  });
});
