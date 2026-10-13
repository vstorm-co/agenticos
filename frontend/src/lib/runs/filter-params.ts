/**
 * How Activity's narrowing travels: as query parameters, in one vocabulary.
 *
 * Every one of these used to be `useState` inside the run history tab, and the
 * cost was not the reload - it was that **no card could hand over to its own
 * rows**. The dashboard says Mattermost 31 and could only ever link to all 58
 * runs, so three of its cards carried no link at all (#768). One module owns
 * both directions now: the page parses the URL into filters, and anything that
 * wants to point at a slice builds the link with {@link runsHref} rather than
 * assembling parameter names of its own.
 *
 * `all` is the absence of a filter, not a value: it is never written to the URL,
 * so a link carries only what it actually narrows and a cleared filter leaves no
 * trace behind in the address bar.
 */

import { formatPeriodParam, type Period } from "@/lib/dashboard/period";
import { ROUTES } from "@/lib/constants";
import { setUrlParam } from "@/lib/utils";
import type { RunStatus } from "@/types/runs";

export interface RunFilters {
  status: RunStatus | "all" | "problems";
  surface: string;
  rated: "all" | "up" | "down";
  userId: string;
  versionId: string;
  /** The model as a run recorded it - the label the dashboard's bars count. */
  model: string;
}

export const DEFAULT_RUN_FILTERS: RunFilters = {
  status: "all",
  surface: "all",
  rated: "all",
  userId: "all",
  versionId: "all",
  model: "all",
};

/** The URL name of each filter. `person` reads better in a pasted link than `userId`. */
const PARAM: Record<keyof RunFilters, string> = {
  status: "status",
  surface: "surface",
  rated: "rated",
  userId: "person",
  versionId: "version",
  model: "model",
};

const RATINGS = new Set(["up", "down"]);

/** Activity's three tabs, in the order the strip draws them. */
export const RUNS_TABS = ["runs", "approvals", "spend"] as const;

export type RunsTab = (typeof RUNS_TABS)[number];

/**
 * Read `?tab=` back, against what the caller may actually open.
 *
 * `approvals` is gated on `approvals:decide`, so a link carrying it that reaches
 * somebody without the permission resolves to the run history rather than to a
 * strip whose selected value has no trigger and no content - which draws as a
 * blank page below the tabs. Anything unrecognised falls back the same way, for
 * the reason {@link parseRunFilters} does: a pasted link naming a tab this build
 * renamed should still open the page.
 */
export function parseRunsTab(param: string | null, canDecide: boolean): RunsTab {
  const tab = RUNS_TABS.find((name) => name === param?.trim()) ?? "runs";
  return tab === "approvals" && !canDecide ? "runs" : tab;
}

/**
 * Read a URL back into filters, forgivingly.
 *
 * Anything unrecognised falls back to "all" rather than to an error: a pasted
 * link with a status this build renamed should still open the page, narrowed by
 * whatever else it carried. `rated` is the one closed set worth checking here -
 * the others are ids and free strings the backend answers for, and a status it
 * does not know is refused by name at the API rather than guessed at here.
 */
export function parseRunFilters(params: URLSearchParams): RunFilters {
  const read = (key: keyof RunFilters) => params.get(PARAM[key])?.trim() || "all";
  const rated = read("rated");
  return {
    status: read("status") as RunFilters["status"],
    surface: read("surface"),
    rated: RATINGS.has(rated) ? (rated as RunFilters["rated"]) : "all",
    userId: read("userId"),
    versionId: read("versionId"),
    model: read("model"),
  };
}

/** Which filters are set, as URL parameters. An `all` contributes nothing. */
export function runFilterParams(filters: Partial<RunFilters>): Record<string, string> {
  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters) as [keyof RunFilters, string][]) {
    if (value && value !== "all") params[PARAM[key]] = value;
  }
  return params;
}

/**
 * Mirror the filters into the address bar - every parameter, set or cleared.
 *
 * Cleared explicitly rather than only written: a filter dropped from the object
 * but left in the URL is one a reload would bring back, which is the shape of
 * bug a person only meets after they thought they had cleared it.
 */
export function writeRunFilters(filters: RunFilters): void {
  const params = runFilterParams(filters);
  for (const name of Object.values(PARAM)) setUrlParam(name, params[name] ?? null);
}

/** Whether anything is narrowed - what the tab says out loud when a list is empty. */
export function isNarrowed(filters: RunFilters): boolean {
  return Object.keys(runFilterParams(filters)).length > 0;
}

/**
 * A link to Activity, narrowed to one slice of one window.
 *
 * This is what a dashboard card hands over with: the same window it counted
 * over, plus the one facet its row names. The window travels as the preset id
 * where there is one (`period=30d` means "the last 30 days on the day it is
 * clicked", not the dates this card happened to resolve this morning) - the form
 * `parsePeriodParam` reads back.
 */
export function runsHref(options: {
  period?: Period;
  filters?: Partial<RunFilters>;
  /** `duration` is the p95 figure's hand-off: the slow runs, slowest first. */
  sort?: "duration";
  agentId?: string;
  /** Which tab to open on. `runs` is the default and is never written. */
  tab?: RunsTab;
}): string {
  const params = new URLSearchParams(runFilterParams(options.filters ?? {}));
  if (options.tab && options.tab !== "runs") params.set("tab", options.tab);
  if (options.agentId) params.set("agent", options.agentId);
  if (options.sort) params.set("sort", options.sort);
  if (options.period) params.set("period", formatPeriodParam(options.period));
  const query = params.toString();
  return query ? `${ROUTES.RUNS}?${query}` : ROUTES.RUNS;
}
