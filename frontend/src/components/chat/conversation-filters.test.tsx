import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ConversationFilters,
  DEFAULT_SORT,
  isConversationSort,
  splitSort,
} from "./conversation-filters";
import type { Agent } from "@/types/agents";

const listedAgents = vi.fn<() => Partial<Agent>[]>(() => []);

vi.mock("@/hooks", () => ({
  useAgents: () => ({ agents: listedAgents() }),
}));
vi.mock("@/components/agents/agent-avatar", () => ({
  AgentAvatar: ({ name }: { name: string }) => <span data-testid="avatar">{name}</span>,
}));

function mount(props: Partial<Parameters<typeof ConversationFilters>[0]> = {}) {
  const onAgentChange = vi.fn();
  const onSortChange = vi.fn();
  const onHideApiChange = vi.fn();
  const onViewChange = vi.fn();
  render(
    <ConversationFilters
      view="active"
      onViewChange={onViewChange}
      agentId={null}
      onAgentChange={onAgentChange}
      sort={DEFAULT_SORT}
      onSortChange={onSortChange}
      hideApi={false}
      onHideApiChange={onHideApiChange}
      {...props}
    />,
  );
  return { onAgentChange, onSortChange, onHideApiChange, onViewChange };
}

/** Everything but the search sits behind one button. */
async function openFilters() {
  await userEvent.click(screen.getByRole("button", { name: "Filter and sort" }));
}

describe("the sort value", () => {
  it("splits into the two parameters the route takes", () => {
    expect(splitSort("title:asc")).toEqual({ sortBy: "title", sortDir: "asc" });
  });

  it.each(["updated_at:desc", "updated_at:asc", "created_at:desc", "title:asc", "title:desc"])(
    "recognises %s as one it offers",
    (sort) => {
      expect(isConversationSort(sort)).toBe(true);
    },
  );

  it.each([
    // The admin listing sorts by these two, and this one may not: neither
    // column is on this page, and the route answers 422 for both.
    ["owner"],
    ["messages"],
    // A shape the sidebar never writes, from a hand-edited URL.
    ["title"],
    ["title:sideways"],
    [null],
  ])("refuses %s, so a hand-typed URL falls back rather than 422s", (sort) => {
    expect(isConversationSort(sort)).toBe(false);
  });
});

describe("the filter bar", () => {
  it("offers every agent the caller may see, retired ones included", async () => {
    // A thread answered by an agent that has since been archived is exactly the
    // one somebody comes to this filter looking for.
    listedAgents.mockReturnValue([
      { id: "a-1", slug: "analyst", name: "Analyst" },
      { id: "a-2", slug: "retired-support", name: "Retired support" },
    ]);
    mount();
    await openFilters();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));

    expect(screen.getByRole("option", { name: /Analyst/ })).toBeVisible();
    expect(screen.getByRole("option", { name: /Retired support/ })).toBeVisible();
  });

  it("hands back the chosen agent's id", async () => {
    listedAgents.mockReturnValue([{ id: "a-1", slug: "analyst", name: "Analyst" }]);
    const { onAgentChange } = mount();
    await openFilters();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));
    await userEvent.click(screen.getByRole("option", { name: /Analyst/ }));

    expect(onAgentChange).toHaveBeenCalledWith("a-1");
  });

  it("hands back null for all of them, rather than the sentinel it renders", async () => {
    // A `Select` cannot hold an empty value, so "every agent" is the string
    // `all` on screen and the absence of a filter everywhere else.
    listedAgents.mockReturnValue([{ id: "a-1", slug: "analyst", name: "Analyst" }]);
    const { onAgentChange } = mount({ agentId: "a-1" });
    await openFilters();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));
    await userEvent.click(screen.getByRole("option", { name: "All agents" }));

    expect(onAgentChange).toHaveBeenCalledWith(null);
  });

  it("says what the agent filter means, only while one is applied", async () => {
    listedAgents.mockReturnValue([{ id: "a-1", slug: "analyst", name: "Analyst" }]);
    mount();
    await openFilters();
    expect(screen.queryByText("Threads this agent answered in")).not.toBeInTheDocument();
  });

  it("says so beside the picker once an agent narrows the list", async () => {
    listedAgents.mockReturnValue([{ id: "a-1", slug: "analyst", name: "Analyst" }]);
    mount({ agentId: "a-1" });
    await openFilters();
    expect(screen.getByText("Threads this agent answered in")).toBeVisible();
  });

  it("marks its button when anything narrows or reorders the list", () => {
    mount({ hideApi: true });
    const button = screen.getByRole("button", { name: "Filter and sort" });
    expect(button.querySelector("span[aria-hidden]")).not.toBeNull();
  });

  it("leaves its button unmarked on the plain list", () => {
    mount();
    const button = screen.getByRole("button", { name: "Filter and sort" });
    expect(button.querySelector("span[aria-hidden]")).toBeNull();
  });

  it("switches to the archive from behind the button", async () => {
    const { onViewChange } = mount();
    await openFilters();
    await userEvent.click(screen.getByRole("button", { name: "Archived" }));
    expect(onViewChange).toHaveBeenCalledWith("archived");
  });

  it("hands back a sort the route will accept", async () => {
    const { onSortChange } = mount();
    await openFilters();

    await userEvent.click(screen.getByRole("combobox", { name: "Sort conversations" }));
    await userEvent.click(screen.getByRole("option", { name: "Title A–Z" }));

    expect(onSortChange).toHaveBeenCalledWith("title:asc");
    expect(isConversationSort(onSortChange.mock.calls[0]?.[0])).toBe(true);
  });
});

describe("conversations opened over the API (#2122)", () => {
  it("hides them with one switch", async () => {
    const { onHideApiChange } = mount();
    await openFilters();
    const toggle = screen.getByRole("switch", { name: "Hide conversations opened over the API" });

    expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    expect(onHideApiChange).toHaveBeenCalledWith(true);
  });

  it("shows them again from the switched-on state", async () => {
    const { onHideApiChange } = mount({ hideApi: true });
    await openFilters();

    await userEvent.click(
      screen.getByRole("switch", { name: "Hide conversations opened over the API" }),
    );
    expect(onHideApiChange).toHaveBeenCalledWith(false);
  });
});
