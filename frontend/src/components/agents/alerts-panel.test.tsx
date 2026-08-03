import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AlertsPanel } from "./alerts-panel";
import { DEFAULT_NOTIFICATIONS } from "@/lib/agent-spec";
import type { NotificationSpec } from "@/types/agents";

const org = vi.hoisted(() => ({
  members: [
    { user_id: "u-1", full_name: "Ada Lovelace", email: "ada@acme.test" },
    { user_id: "u-2", full_name: null, email: "bob@acme.test" },
  ] as { user_id: string; full_name: string | null; email: string }[],
}));

vi.mock("@/hooks", () => ({ useMembers: () => ({ members: org.members }) }));

vi.mock("@/stores", () => ({ useOrgStore: () => "org-1" }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mount(value: NotificationSpec | undefined = DEFAULT_NOTIFICATIONS, disabled = false) {
  const onChange = vi.fn();
  render(<AlertsPanel value={value} onChange={onChange} disabled={disabled} />, { wrapper });
  return { onChange };
}

beforeEach(() => {
  org.members = [
    { user_id: "u-1", full_name: "Ada Lovelace", email: "ada@acme.test" },
    { user_id: "u-2", full_name: null, email: "bob@acme.test" },
  ];
});

/** The spec the panel would save after one interaction. */
function saved(onChange: ReturnType<typeof vi.fn>): NotificationSpec {
  return onChange.mock.calls.at(-1)?.[0] as NotificationSpec;
}

/** An alert set to mail named people, which is the only state members appear in. */
function withChosen(userIds: string[]): NotificationSpec {
  return {
    ...DEFAULT_NOTIFICATIONS,
    approvals: { enabled: true, to: ["chosen"], user_ids: userIds },
  };
}

describe("the alerts panel", () => {
  it("shows the shipped defaults for an agent that has never been saved", () => {
    // A spec created in this session carries no notification block. Rendering
    // "nothing is set" for an agent that will in fact mail the admins would be
    // the wrong answer to the only question this panel asks.
    mount(undefined);

    expect(screen.getByRole("switch", { name: "Budget alerts" })).toBeChecked();
    expect(screen.getByRole("switch", { name: "Approval requests" })).toBeChecked();
    expect(screen.getByRole("switch", { name: "Usage reports" })).not.toBeChecked();
  });

  it("does not offer the run's initiator for a usage report", () => {
    // A report covers a period, not a run, so there is no such person - and the
    // backend refuses it. Offering it would be offering a save that fails.
    mount();

    expect(
      screen.queryByRole("checkbox", { name: "Usage reports: Whoever started the run" }),
    ).toBeNull();
    expect(
      screen.getByRole("checkbox", { name: "Approval requests: Whoever started the run" }),
    ).toBeInTheDocument();
  });

  it("switching an alert off leaves its audience alone", async () => {
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("switch", { name: "Budget alerts" }));

    expect(saved(onChange).budget.enabled).toBe(false);
    expect(saved(onChange).budget.to).toEqual(["admins", "owner"]);
  });

  it("switching an alert on with no audience brings one back", async () => {
    // The backend refuses an enabled alert with an empty `to`, so the panel must
    // not be able to produce one by clicking.
    const emptied: NotificationSpec = {
      ...DEFAULT_NOTIFICATIONS,
      usage: { enabled: false, to: [], user_ids: [] },
    };
    const { onChange } = mount(emptied);

    await userEvent.click(screen.getByRole("switch", { name: "Usage reports" }));

    expect(saved(onChange).usage.enabled).toBe(true);
    expect(saved(onChange).usage.to).toEqual(["admins"]);
  });

  it("dropping the chosen audience drops the people named under it", async () => {
    // Ids without `chosen` in `to` are refused by the backend, so leaving them
    // behind would make the next save fail on a field nobody can see.
    const { onChange } = mount(withChosen(["u-1"]));

    await userEvent.click(
      screen.getByRole("checkbox", { name: "Approval requests: Specific people" }),
    );

    expect(saved(onChange).approvals.to).toEqual([]);
    expect(saved(onChange).approvals.user_ids).toEqual([]);
  });

  it("names members by their name, falling back to the address", async () => {
    // In a menu rather than as a pill each: an organization of forty rendered
    // forty of them inside a settings card, which is what made this section the
    // odd one out in the app.
    mount(withChosen(["u-1"]));

    await userEvent.click(screen.getByRole("button", { name: /1 person/ }));

    expect(
      screen.getByRole("menuitemcheckbox", { name: "Approval requests: Ada Lovelace" }),
    ).toBeChecked();
    expect(
      screen.getByRole("menuitemcheckbox", { name: "Approval requests: bob@acme.test" }),
    ).not.toBeChecked();
  });

  it("lists who was chosen without opening the menu", () => {
    // Who is on the list is what somebody scanning the page wants, and a count on
    // a closed menu does not answer it.
    mount(withChosen(["u-1"]));

    expect(screen.getByRole("listitem")).toHaveTextContent("Ada Lovelace");
  });

  it("says so when an enabled alert would mail nobody", async () => {
    // Reachable by clicking - switch an alert on, then clear its audiences - and
    // the save would be refused with a message about a field the author cannot
    // see from here.
    const nobody: NotificationSpec = {
      ...DEFAULT_NOTIFICATIONS,
      approvals: { enabled: true, to: [], user_ids: [] },
    };
    mount(nobody);

    expect(screen.getByText(/Nobody is set to hear this/)).toBeInTheDocument();
  });

  it("says so when specific people are chosen and nobody is named", () => {
    const nobodyNamed: NotificationSpec = {
      ...DEFAULT_NOTIFICATIONS,
      approvals: { enabled: true, to: ["chosen"], user_ids: [] },
    };
    mount(nobodyNamed);

    expect(screen.getByText(/nobody is named/)).toBeInTheDocument();
  });

  it("keeps the organization's own cap off this panel", () => {
    // It stops every agent in the organization and an agent's author cannot
    // raise it, so no agent may redirect or silence its alert.
    mount();

    expect(screen.getByText(/organization's own monthly cap is not here/)).toBeInTheDocument();
  });

  it("names a person to hear the alert", async () => {
    const { onChange } = mount(withChosen(["u-1"]));

    await userEvent.click(screen.getByRole("button", { name: /1 person/ }));
    await userEvent.click(
      screen.getByRole("menuitemcheckbox", { name: "Approval requests: bob@acme.test" }),
    );

    expect(saved(onChange).approvals.user_ids).toEqual(["u-1", "u-2"]);
  });

  it("takes a person back off the list", async () => {
    // From the row rather than the menu: it is what somebody looking at the list
    // has in front of them.
    const { onChange } = mount(withChosen(["u-1", "u-2"]));

    await userEvent.click(
      screen.getByRole("button", { name: "Approval requests: remove Ada Lovelace" }),
    );

    expect(saved(onChange).approvals.user_ids).toEqual(["u-2"]);
  });

  it("says an organization of one has nobody to choose from", () => {
    // Otherwise the panel shows an empty row and the warning below it reads as a
    // bug rather than as the truth: there is nobody else here.
    org.members = [];
    mount(withChosen([]));

    expect(
      screen.getByText("No members to choose from - this organization is just you."),
    ).toBeInTheDocument();
  });

  it("accepts nothing from somebody who cannot edit the spec", async () => {
    const { onChange } = mount(withChosen(["u-1"]), true);

    await userEvent.click(screen.getByRole("switch", { name: "Approval requests" }));
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Approval requests: Specific people" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Approval requests: remove Ada Lovelace" }),
    );

    expect(onChange).not.toHaveBeenCalled();
  });

  it("adds an audience to one already set", async () => {
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("checkbox", { name: "Budget alerts: Specific people" }));

    expect(saved(onChange).budget.to).toEqual(["admins", "owner", "chosen"]);
  });
});
