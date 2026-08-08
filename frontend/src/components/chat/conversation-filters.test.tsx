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
  const onSearchChange = vi.fn();
  const onAgentChange = vi.fn();
  const onSortChange = vi.fn();
  render(
    <ConversationFilters
      search=""
      onSearchChange={onSearchChange}
      agentId={null}
      onAgentChange={onAgentChange}
      sort={DEFAULT_SORT}
      onSortChange={onSortChange}
      {...props}
    />,
  );
  return { onSearchChange, onAgentChange, onSortChange };
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
  it("reports what was typed, without deciding when to ask for it", () => {
    // Debouncing belongs to the sidebar, which owns the request. This reports
    // every keystroke so the box stays responsive under a slow list.
    const { onSearchChange } = mount();

    const box = screen.getByRole("textbox", { name: "Search conversations" });
    box.focus();

    expect(box).toHaveValue("");
    expect(onSearchChange).not.toHaveBeenCalled();
  });

  it("offers every agent the caller may see, retired ones included", async () => {
    // A thread answered by an agent that has since been archived is exactly the
    // one somebody comes to this filter looking for.
    listedAgents.mockReturnValue([
      { id: "a-1", name: "Analyst" },
      { id: "a-2", name: "Retired support" },
    ]);
    mount();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));

    expect(screen.getByRole("option", { name: /Analyst/ })).toBeVisible();
    expect(screen.getByRole("option", { name: /Retired support/ })).toBeVisible();
  });

  it("hands back the chosen agent's id", async () => {
    listedAgents.mockReturnValue([{ id: "a-1", name: "Analyst" }]);
    const { onAgentChange } = mount();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));
    await userEvent.click(screen.getByRole("option", { name: /Analyst/ }));

    expect(onAgentChange).toHaveBeenCalledWith("a-1");
  });

  it("hands back null for all of them, rather than the sentinel it renders", async () => {
    // A `Select` cannot hold an empty value, so "every agent" is the string
    // `all` on screen and the absence of a filter everywhere else.
    listedAgents.mockReturnValue([{ id: "a-1", name: "Analyst" }]);
    const { onAgentChange } = mount({ agentId: "a-1" });

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));
    await userEvent.click(screen.getByRole("option", { name: "All agents" }));

    expect(onAgentChange).toHaveBeenCalledWith(null);
  });

  it("says what the agent filter means, only while one is applied", () => {
    listedAgents.mockReturnValue([{ id: "a-1", name: "Analyst" }]);
    const { rerender } = render(
      <ConversationFilters
        search=""
        onSearchChange={vi.fn()}
        agentId={null}
        onAgentChange={vi.fn()}
        sort={DEFAULT_SORT}
        onSortChange={vi.fn()}
      />,
    );
    expect(screen.queryByText("Threads this agent answered in")).not.toBeInTheDocument();

    rerender(
      <ConversationFilters
        search=""
        onSearchChange={vi.fn()}
        agentId="a-1"
        onAgentChange={vi.fn()}
        sort={DEFAULT_SORT}
        onSortChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Threads this agent answered in")).toBeVisible();
  });

  it("hands back a sort the route will accept", async () => {
    const { onSortChange } = mount();

    await userEvent.click(screen.getByRole("combobox", { name: "Sort conversations" }));
    await userEvent.click(screen.getByRole("option", { name: "Title A–Z" }));

    expect(onSortChange).toHaveBeenCalledWith("title:asc");
    expect(isConversationSort(onSortChange.mock.calls[0]?.[0])).toBe(true);
  });

  it("leaves the search box no fixed width to overflow the sidebar with", () => {
    // `SearchInput` defaults to `sm:w-64` for the wide pages every other caller
    // sits on. The sidebar is `w-64` itself, so from the `sm` breakpoint up that
    // default made the box 24px wider than the column holding it and it hung
    // over the right edge. jsdom lays nothing out, so the class is the only
    // observable the bug leaves behind.
    mount();

    const box = screen.getByRole("textbox", { name: "Search conversations" });
    expect(box.parentElement?.className).not.toMatch(/(^|:)w-64\b/);
  });
});
