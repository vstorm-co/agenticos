import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { DEFAULT_RUN_FILTERS, RunFilterBar } from "./run-filter-bar";

/**
 * Who is offered which filter.
 *
 * The agent and version selects fill their options from `/agents`, which takes
 * `agents:view` - rendered for a caller without it, they would be menus whose
 * request 403s. The person select's options are the member list, which any
 * member may read, so its gate is only having an organization to ask about.
 * The narrowing behaviour itself is proven through the tab's tests, where the
 * values reach `useRuns`.
 */

const perm = vi.hoisted(() => ({ agentsView: true }));
const org = vi.hoisted(() => ({ activeOrgId: "org-1" as string | null }));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: (p: string) => p !== "agents:view" || perm.agentsView }),
  useAgents: () => ({ agents: [{ id: "agent-1", name: "Support agent" }], isLoading: false }),
  useAgentVersions: () => ({ versions: [{ id: "ver-1", version: 1 }], isLoading: false }),
  useAllAgentVersions: () => ({ versions: [{ id: "ver-1", version: 1 }], isLoading: false }),
  useMembers: () => ({ members: [] }),
  // The model facet's vocabulary is the window's own labels; an empty window
  // renders no select at all, which is what these gate specs expect.
  useUsageStats: () => ({ usage: usage.value, isLoading: false, isStale: false, error: null }),
}));

const PERIOD = { preset: "30d", from: "2026-07-16", to: "2026-08-14" } as const;

/** What the window recorded, which is where the model facet's options come from. */
const usage: { value: { by_model: { model_label: string | null; runs: number }[] } | null } = {
  value: null,
};
vi.mock("@/stores", () => ({
  useOrgStore: (selector: (state: { activeOrgId: string | null }) => unknown) => selector(org),
}));

function renderBar(agentId: string | null = "agent-1", filters = DEFAULT_RUN_FILTERS) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RunFilterBar
        filters={filters}
        period={PERIOD}
        onChange={vi.fn()}
        agentId={agentId}
        onAgentChange={vi.fn()}
      />
    </NextIntlClientProvider>,
  );
}

describe("the filter bar's gates", () => {
  it("offers every filter to a caller who may fill them all", () => {
    perm.agentsView = true;
    org.activeOrgId = "org-1";
    renderBar();

    for (const name of [
      "Filter by status",
      "Filter by surface",
      "Filter by rating",
      "Filter by agent",
      "Filter by person",
      "Filter by version",
    ]) {
      expect(screen.getByRole("combobox", { name })).toBeVisible();
    }
  });

  it("withholds the agent and version selects without agents:view", () => {
    perm.agentsView = false;
    org.activeOrgId = "org-1";
    renderBar();

    expect(screen.queryByRole("combobox", { name: "Filter by agent" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Filter by version" })).toBeNull();
    expect(screen.getByRole("combobox", { name: "Filter by status" })).toBeVisible();
  });

  it("withholds the person select with no organization to list members of", () => {
    perm.agentsView = true;
    org.activeOrgId = null;
    renderBar();

    expect(screen.queryByRole("combobox", { name: "Filter by person" })).toBeNull();
  });

  it("withholds the version select when no agent narrows the history", () => {
    perm.agentsView = true;
    org.activeOrgId = "org-1";
    renderBar(null);

    expect(screen.queryByRole("combobox", { name: "Filter by version" })).toBeNull();
  });
});

describe("the model facet", () => {
  it("offers the labels the window actually recorded, not the model catalog", async () => {
    // A run stores the label it ran with, and a profile that has since been
    // renamed or deleted still has runs behind it - so the vocabulary is the
    // window's own, which is what makes the dashboard's bar and this facet the
    // same set.
    usage.value = {
      by_model: [
        { model_label: "gpt-4o-mini", runs: 3 },
        { model_label: "claude-sonnet-5", runs: 2 },
        // A run that recorded no label cannot be asked for by one: the filter
        // matches the column, and "not recorded" is its absence.
        { model_label: null, runs: 1 },
      ],
    };
    renderBar();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by model" }));

    expect(await screen.findByRole("option", { name: "gpt-4o-mini" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "claude-sonnet-5" })).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(3);
  });

  it("is not rendered for a window with nothing to choose between", () => {
    // One model, or none: a facet whose only choice is the set you already have.
    usage.value = { by_model: [{ model_label: "gpt-4o-mini", runs: 3 }] };
    renderBar();

    expect(screen.queryByRole("combobox", { name: "Filter by model" })).toBeNull();
  });

  it("keeps a model the window has no runs of, when a link narrowed to it", async () => {
    // A card links here with `?model=`; if the window since moved past those
    // runs the facet still has to say what it is showing - and be clearable.
    usage.value = { by_model: [{ model_label: "gpt-4o-mini", runs: 3 }] };
    renderBar("agent-1", { ...DEFAULT_RUN_FILTERS, model: "claude-sonnet-5" });

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by model" }));

    expect(await screen.findByRole("option", { name: "claude-sonnet-5" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Any model" })).toBeInTheDocument();
  });
});
