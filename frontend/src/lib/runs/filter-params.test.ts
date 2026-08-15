import { describe, expect, it } from "vitest";

import {
  DEFAULT_RUN_FILTERS,
  isNarrowed,
  parseRunFilters,
  runFilterParams,
  runsHref,
  type RunFilters,
} from "./filter-params";

/**
 * The round-trip is the feature: a narrowing that cannot be written into a link
 * is a dashboard card that cannot hand over to its own runs (#768). So what is
 * held shut here is that every filter survives the trip in both directions,
 * that an unset one leaves no trace, and that a link built for a slice carries
 * the window it was counted over.
 */

const narrowed: RunFilters = {
  status: "failed",
  surface: "mattermost",
  rated: "down",
  userId: "user-1",
  versionId: "ver-2",
  model: "gpt-4o-mini",
};

describe("run filters in the URL", () => {
  it("survives the round-trip whole", () => {
    const params = new URLSearchParams(runFilterParams(narrowed));

    expect(parseRunFilters(params)).toEqual(narrowed);
  });

  it("writes nothing for a filter that is not set", () => {
    // `all` is the absence of a filter, so an unnarrowed page has a clean URL
    // and a link carries only what it actually narrows.
    expect(runFilterParams(DEFAULT_RUN_FILTERS)).toEqual({});
    expect(isNarrowed(DEFAULT_RUN_FILTERS)).toBe(false);
    expect(isNarrowed({ ...DEFAULT_RUN_FILTERS, surface: "slack" })).toBe(true);
  });

  it("reads a person by the name a pasted link uses", () => {
    expect(parseRunFilters(new URLSearchParams("person=user-9")).userId).toBe("user-9");
    expect(runFilterParams({ userId: "user-9" })).toEqual({ person: "user-9" });
  });

  it("falls back to unnarrowed rather than erroring on nonsense", () => {
    // A pasted link with a rating this build does not have should still open
    // the page, narrowed by whatever else it carried.
    const filters = parseRunFilters(new URLSearchParams("rated=sideways&surface=slack"));

    expect(filters.rated).toBe("all");
    expect(filters.surface).toBe("slack");
  });

  it("reads an empty parameter as no filter at all", () => {
    expect(parseRunFilters(new URLSearchParams("surface=&status=  ")).surface).toBe("all");
  });
});

describe("a link to a slice", () => {
  const period = { preset: "90d", from: "2026-05-18", to: "2026-08-15" } as const;

  it("carries the window as its preset, not as the dates it resolved to", () => {
    // `period=90d` means "the last 90 days on the day it is clicked". Freezing
    // the dates would make a link that ages into somebody else's window.
    const href = runsHref({ period, filters: { surface: "mattermost" } });

    expect(href).toContain("surface=mattermost");
    expect(href).toContain("period=90d");
    expect(href).not.toContain("2026-05-18");
  });

  it("carries an agent and a sort where a card hands those over", () => {
    const href = runsHref({ period, agentId: "agent-1", sort: "duration" });

    expect(href).toContain("agent=agent-1");
    expect(href).toContain("sort=duration");
  });

  it("is the plain runs page when nothing narrows it", () => {
    expect(runsHref({})).toBe("/runs");
  });
});
