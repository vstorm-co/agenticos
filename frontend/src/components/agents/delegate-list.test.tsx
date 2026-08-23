import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DelegateList } from "./delegate-list";
import type { Agent, AgentVersion, SubagentRef } from "@/types/agents";

const state = vi.hoisted(() => ({ versions: [] as AgentVersion[] }));

vi.mock("@/hooks", () => ({
  useAllAgentVersions: (agentId: string | null) => ({
    // `null` is how the row says it has no agent to ask about; answering with a
    // history anyway would hide that the query is skipped.
    versions: agentId === null ? [] : state.versions,
    isLoading: false,
  }),
}));

function agent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "a1",
    slug: "researcher",
    name: "Researcher",
    description: null,
    status: "published",
    visibility: "private",
    owner_user_id: null,
    current_version_id: "v7",
    can_run: false,
    ...overrides,
  };
}

function version(number: number): AgentVersion {
  return { id: `v${number}`, version: number, note: null, published_by_user_id: null };
}

function mount({
  agents = [agent()],
  subagents = [] as SubagentRef[],
  clashes = new Set<string>(),
  canDelegate = true,
  disabled = false,
  onChange = vi.fn(),
}: {
  agents?: Agent[];
  subagents?: SubagentRef[];
  clashes?: Set<string>;
  canDelegate?: boolean;
  disabled?: boolean;
  onChange?: (subagents: SubagentRef[]) => void;
} = {}) {
  render(
    <DelegateList
      agents={agents}
      subagents={subagents}
      onChange={onChange}
      clashes={clashes}
      canDelegate={canDelegate}
      disabled={disabled}
    />,
  );
  return onChange;
}

beforeEach(() => {
  state.versions = [version(7), version(5), version(3)];
});

describe("choosing a delegate", () => {
  it("offers only an agent with a version to pin", async () => {
    // The pin is the whole reason the reference exists, and a draft has nothing
    // to pin - so offering one would be offering a spec that cannot be written.
    mount({ agents: [agent(), agent({ id: "a2", name: "Draft", current_version_id: null })] });

    await userEvent.click(screen.getByRole("button", { name: "Add a delegate" }));

    expect(screen.getByRole("menuitem", { name: /Researcher/ })).toBeVisible();
    expect(screen.queryByRole("menuitem", { name: /Draft/ })).toBeNull();
  });

  it("does not offer an archived agent, which has stopped answering", async () => {
    // It keeps its version id, so the pin would be writable and useless.
    mount({
      agents: [agent(), agent({ id: "a2", name: "Retired", status: "archived" })],
    });

    await userEvent.click(screen.getByRole("button", { name: "Add a delegate" }));

    expect(screen.queryByRole("menuitem", { name: /Retired/ })).toBeNull();
  });

  it("does not offer an agent that is already a delegate", async () => {
    // Two pins of one agent are two delegates with one name, which the spec's
    // own validator refuses before the request is made.
    mount({ subagents: [{ agent_id: "a1", agent_version_id: "v7" }] });

    await userEvent.click(screen.getByRole("button", { name: "Add a delegate" }));

    expect(screen.queryByRole("menuitem", { name: /Researcher/ })).toBeNull();
  });

  it("pins the version the delegate publishes now", async () => {
    const onChange = mount();

    await userEvent.click(screen.getByRole("button", { name: "Add a delegate" }));
    await userEvent.click(screen.getByRole("menuitem", { name: /Researcher/ }));

    expect(onChange).toHaveBeenCalledWith([{ agent_id: "a1", agent_version_id: "v7" }]);
  });

  it("has nothing to offer when the organization has published nothing", () => {
    mount({ agents: [] });

    expect(screen.getByRole("button", { name: "Add a delegate" })).toBeDisabled();
    expect(screen.getByText(/Only a published agent can be one/)).toBeVisible();
  });

  it("does not render the picker for somebody who may not run agents", () => {
    // Publishing checks each delegate against the publisher's own access, so a
    // control here would be a dead end with a delay on it.
    mount({ canDelegate: false });

    expect(screen.queryByRole("button", { name: "Add a delegate" })).toBeNull();
    expect(screen.getByText(/needs permission to run agents/)).toBeVisible();
  });
});

/**
 * The pin, and how far it has fallen behind.
 *
 * The single most important thing on this panel. Pinning is what keeps a
 * delegate's behaviour stable under a published parent; the cost is that a fix
 * to the delegate does not arrive, and without this row "why did the fix to the
 * researcher not take effect" has no answer anywhere in the product.
 */
describe("staleness", () => {
  it("says how far behind a pin is, and what the delegate publishes now", () => {
    mount({ subagents: [{ agent_id: "a1", agent_version_id: "v3" }] });

    expect(screen.getByText("4 behind")).toBeVisible();
    expect(
      screen.getByText(/pinned at v3, and v7 is what this delegate publishes now/),
    ).toBeVisible();
  });

  it("counts a single version behind as one, not as 1 versions", () => {
    state.versions = [version(7), version(6)];
    mount({ subagents: [{ agent_id: "a1", agent_version_id: "v6" }] });

    expect(screen.getByText(/^One version behind/)).toBeVisible();
  });

  it("moving to the latest rewrites the pin and nothing else", async () => {
    const onChange = mount({
      subagents: [{ agent_id: "a1", agent_version_id: "v3", preferred_mode: "async" }],
    });

    await userEvent.click(screen.getByRole("button", { name: "Update to latest" }));

    expect(onChange).toHaveBeenCalledWith([
      { agent_id: "a1", agent_version_id: "v7", preferred_mode: "async" },
    ]);
  });

  it("offers nothing to update on a pin that is already current", () => {
    mount({ subagents: [{ agent_id: "a1", agent_version_id: "v7" }] });

    expect(screen.getByText("v7, current")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Update to latest" })).toBeNull();
  });

  it("says a pin whose version is gone fails the run, and offers the way out", async () => {
    // Deliberately not a quiet fall back to the current version: the reason to
    // pin is that nothing changes without a decision.
    state.versions = [version(7)];
    const onChange = mount({ subagents: [{ agent_id: "a1", agent_version_id: "v2" }] });

    expect(screen.getByText("Version gone")).toBeVisible();
    expect(screen.getByText(/a run that reaches this delegate fails and names it/)).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Update to latest" }));
    expect(onChange).toHaveBeenCalledWith([{ agent_id: "a1", agent_version_id: "v7" }]);
  });

  it("claims nothing about a pin whose history it could not read", () => {
    state.versions = [];
    mount({ subagents: [{ agent_id: "a1", agent_version_id: "v3" }] });

    expect(screen.getByText("History unread")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Update to latest" })).toBeNull();
  });
});

describe("what publishing would refuse, said here instead", () => {
  it("names the agent pinned twice", () => {
    // Reachable from an imported or hand-written spec, and from nothing this
    // picker can do - which is why the row says so rather than the picker.
    mount({
      subagents: [
        { agent_id: "a1", agent_version_id: "v7" },
        { agent_id: "a1", agent_version_id: "v5" },
      ],
    });

    expect(screen.getAllByText(/Pinned twice/)).toHaveLength(2);
  });

  it("names a delegate whose handle something else here also answers to", () => {
    mount({
      subagents: [{ agent_id: "a1", agent_version_id: "v7" }],
      clashes: new Set(["researcher"]),
    });

    expect(screen.getByText(/also called researcher/)).toBeVisible();
  });

  it("says a delegate it cannot see will be refused rather than dropping it", () => {
    // A silently shorter list hides exactly the problem that refuses at publish.
    mount({ subagents: [{ agent_id: "gone-1", agent_version_id: "v7" }] });

    expect(screen.getByText("An agent you cannot see")).toBeVisible();
    expect(screen.getByText("gone-1")).toBeVisible();
    expect(screen.getByText(/Publishing will refuse it either way/)).toBeVisible();
  });
});

describe("the rest of a delegate row", () => {
  it("removes the delegate it names, not the first one", async () => {
    const onChange = mount({
      agents: [agent(), agent({ id: "a2", slug: "writer", name: "Writer" })],
      subagents: [
        { agent_id: "a1", agent_version_id: "v7" },
        { agent_id: "a2", agent_version_id: "v7" },
      ],
    });

    await userEvent.click(screen.getByRole("button", { name: "Remove Writer" }));

    expect(onChange).toHaveBeenCalledWith([{ agent_id: "a1", agent_version_id: "v7" }]);
  });

  it("stores an override of the policy's mode for this delegate alone", async () => {
    // For *this* delegate: the row writes into one entry of the list, and a
    // sibling that comes out changed is a sibling somebody did not touch.
    const onChange = mount({
      agents: [agent(), agent({ id: "a2", slug: "writer", name: "Writer" })],
      subagents: [
        { agent_id: "a1", agent_version_id: "v7" },
        { agent_id: "a2", agent_version_id: "v7" },
      ],
    });

    const row = screen.getByRole("listitem", { name: "writer" });
    await userEvent.click(within(row).getByRole("combobox", { name: "When it hands back" }));
    await userEvent.click(screen.getByRole("option", { name: "Start it and carry on" }));

    expect(onChange).toHaveBeenCalledWith([
      { agent_id: "a1", agent_version_id: "v7" },
      { agent_id: "a2", agent_version_id: "v7", preferred_mode: "async" },
    ]);
  });

  it("stores following the policy as no override at all", async () => {
    // So changing the policy moves every delegate that never disagreed with it.
    const onChange = mount({
      subagents: [{ agent_id: "a1", agent_version_id: "v7", preferred_mode: "async" }],
    });

    await userEvent.click(screen.getByRole("combobox", { name: "When it hands back" }));
    await userEvent.click(screen.getByRole("option", { name: "Follow the policy" }));

    expect(onChange).toHaveBeenCalledWith([
      { agent_id: "a1", agent_version_id: "v7", preferred_mode: null },
    ]);
  });

  it("is inert for somebody who may not edit the agent", () => {
    mount({ subagents: [{ agent_id: "a1", agent_version_id: "v3" }], disabled: true });

    expect(screen.getByRole("button", { name: "Add a delegate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Update to latest" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove Researcher" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "When it hands back" })).toBeDisabled();
  });
});
