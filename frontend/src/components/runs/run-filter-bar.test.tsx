import { render, screen } from "@testing-library/react";
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
  useMembers: () => ({ members: [] }),
}));
vi.mock("@/stores", () => ({
  useOrgStore: (selector: (state: { activeOrgId: string | null }) => unknown) => selector(org),
}));

function renderBar(agentId: string | null = "agent-1") {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RunFilterBar
        filters={DEFAULT_RUN_FILTERS}
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
