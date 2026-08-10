import { describe, expect, it } from "vitest";

import { completedShare, formatCompletedShare, statusTally, versionTally } from "./run-outcomes";
import type { RunStatus } from "@/types/runs";
import type { StatusCount, VersionUsageRow } from "@/types/stats";

/**
 * One window of runs, expressed as the two shapes the two surfaces read: the
 * donut's per-status counts, and the version strip's single per-version row.
 * Both are derived from the same list, so a divergence in the shares can only
 * come from the arithmetic under test, not from the fixture.
 */
function fromRuns(statuses: RunStatus[]): { byStatus: StatusCount[]; version: VersionUsageRow } {
  const counts = new Map<RunStatus, number>();
  for (const status of statuses) counts.set(status, (counts.get(status) ?? 0) + 1);
  return {
    byStatus: [...counts].map(([status, runs]) => ({ status, runs })),
    version: {
      agent_version_id: "version-1",
      version: 1,
      runs: statuses.length,
      completed_runs: statuses.filter((status) => status === "completed").length,
      p95_ms: null,
      avg_cost_usd: null,
      like_count: 0,
      rating_count: 0,
    },
  };
}

describe("completedShare", () => {
  it("is completed over the total", () => {
    expect(completedShare({ completed: 3, total: 4 })).toBe(0.75);
  });

  it("is null for an empty window rather than zero", () => {
    // A share of no runs is unknown, not 0% - the caller renders the two apart.
    expect(completedShare({ completed: 0, total: 0 })).toBeNull();
  });
});

describe("statusTally", () => {
  it("counts every status in the denominator, cancelled and budget_exceeded included", () => {
    const tally = statusTally([
      { status: "completed", runs: 1 },
      { status: "cancelled", runs: 1 },
      { status: "budget_exceeded", runs: 1 },
    ]);
    // The one invariant this whole module exists for: nothing is excluded, so
    // the denominator is three and the share is a third, not a half.
    expect(tally).toEqual({ completed: 1, total: 3 });
    expect(completedShare(tally)).toBe(1 / 3);
    expect(completedShare(tally)).not.toBe(1 / 2);
  });

  it("is empty for no rows", () => {
    expect(statusTally([])).toEqual({ completed: 0, total: 0 });
  });
});

describe("versionTally", () => {
  it("is the row's completed runs over all of its runs", () => {
    expect(versionTally({ runs: 3, completed_runs: 1 })).toEqual({ completed: 1, total: 3 });
  });
});

describe("formatCompletedShare", () => {
  it("is a whole-number percent", () => {
    expect(formatCompletedShare(1 / 3, "en")).toBe("33%");
    expect(formatCompletedShare(0.9, "en")).toBe("90%");
  });

  it("is a dash for an empty window", () => {
    expect(formatCompletedShare(null)).toBe("—");
  });
});

describe("the version strip and the Outcomes donut agree on the same rows", () => {
  it("read one completed share, with cancelled counted in both denominators", () => {
    // §8a.4: a window of one completed, one cancelled and one budget_exceeded
    // run. The two surfaces read one `by_status`; if either started excluding a
    // status this equality would break, which is the drift the test prevents.
    const { byStatus, version } = fromRuns(["completed", "cancelled", "budget_exceeded"]);

    const donutShare = completedShare(statusTally(byStatus));
    const stripShare = completedShare(versionTally(version));

    expect(donutShare).toBe(1 / 3);
    expect(stripShare).toBe(donutShare);
    expect(formatCompletedShare(stripShare, "en")).toBe(formatCompletedShare(donutShare, "en"));
  });

  it("agree when every run completed, and when the window is empty", () => {
    const all = fromRuns(["completed", "completed"]);
    expect(completedShare(versionTally(all.version))).toBe(
      completedShare(statusTally(all.byStatus)),
    );

    const none = fromRuns([]);
    expect(completedShare(versionTally(none.version))).toBe(
      completedShare(statusTally(none.byStatus)),
    );
  });
});
