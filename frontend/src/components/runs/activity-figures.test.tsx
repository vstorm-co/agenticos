import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActivityFigures } from "./activity-figures";
import type { Period } from "@/lib/dashboard/period";

/**
 * The three figures at the top of the Activity page.
 *
 * Two claims worth proving at this level. Every figure is a claim about the
 * organization, so none of them may print its honest-looking zero while its own
 * query is still in flight - the Waiting figure did exactly that, gated on the
 * other two queries' loading and not its own. And a caller without `runs:view`
 * is not asked for at all: both requests would be predictable 403s, drawn as
 * failure cards about a page that never had anything to show them.
 */

const useSpendMock = vi.fn();
const useRunsMock = vi.fn();
const useApprovalsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useSpend: (range: unknown, options?: unknown) => useSpendMock(range, options),
  useRuns: (agentId?: string, options?: unknown) => useRunsMock(agentId, options),
  useApprovals: (options?: unknown) => useApprovalsMock(options),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-16", to: "2026-08-14" };

const answered = {
  spend: {
    spend: { by_agent: [{ cost_usd: "12.40" }] },
    isLoading: false,
    error: null,
  },
  runs: { total: 8, isLoading: false, error: null },
  approvals: { total: 3, isLoading: false, error: null },
};

beforeEach(() => {
  useSpendMock.mockReset().mockReturnValue(answered.spend);
  useRunsMock.mockReset().mockReturnValue(answered.runs);
  useApprovalsMock.mockReset().mockReturnValue(answered.approvals);
});

describe("the Waiting figure's own loading", () => {
  it("keeps the skeleton up while the approvals query is still in flight", () => {
    // "0 waiting" is what a drained queue looks like; drawn for a request still
    // in flight it sends an approver away from a queue with work in it.
    useApprovalsMock.mockReturnValue({ total: 0, isLoading: true, error: null });

    render(<ActivityFigures canView canDecide period={PERIOD} />);

    expect(screen.queryByText("Waiting on a person")).toBeNull();
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
  });

  it("prints the count once the queue has answered", () => {
    render(<ActivityFigures canView canDecide period={PERIOD} />);

    expect(screen.getByText("Waiting on a person")).toBeVisible();
    expect(screen.getByText("3")).toBeVisible();
  });

  it("does not wait on a queue the caller may not read", () => {
    // Without `approvals:decide` the query is disabled and there is no Waiting
    // figure - its loading state must not hold the other two hostage.
    useApprovalsMock.mockReturnValue({ total: 0, isLoading: true, error: null });

    render(<ActivityFigures canView canDecide={false} period={PERIOD} />);

    expect(screen.getByText("$12.40")).toBeVisible();
    expect(screen.queryByText("Waiting on a person")).toBeNull();
  });
});

describe("a caller without runs:view", () => {
  it("disables both queries and says whose decision the absence is", () => {
    render(<ActivityFigures canView={false} canDecide={false} period={PERIOD} />);

    expect(useSpendMock).toHaveBeenCalledWith(expect.anything(), { enabled: false });
    expect(useRunsMock).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({ enabled: false }),
    );
    expect(screen.getByText("No access to run activity")).toBeVisible();
    expect(screen.queryByText("Couldn't load")).toBeNull();
  });

  it("asks normally for a holder", () => {
    render(<ActivityFigures canView canDecide={false} period={PERIOD} />);

    expect(useSpendMock).toHaveBeenCalledWith(expect.anything(), { enabled: true });
    expect(useRunsMock).toHaveBeenCalledWith(undefined, expect.objectContaining({ enabled: true }));
    expect(screen.getByText("$12.40")).toBeVisible();
  });
});
