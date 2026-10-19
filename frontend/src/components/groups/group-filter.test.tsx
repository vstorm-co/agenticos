import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GroupFilter, NothingSharedWithGroup } from "./group-filter";
import type { Group } from "@/types/groups";

const state = vi.hoisted(() => ({ groups: [] as Group[], orgIds: [] as string[] }));
vi.mock("@/hooks", () => ({
  useGroups: (orgId: string) => {
    state.orgIds.push(orgId);
    return { groups: state.groups };
  },
}));

function group(id: string, name: string): Group {
  return {
    id,
    organization_id: "org-1",
    name,
    description: null,
    icon: null,
    monthly_budget_usd: null,
    member_count: 1,
    created_at: "2026-10-13T00:00:00Z",
  };
}

beforeEach(() => {
  state.groups = [];
  state.orgIds = [];
});

describe("GroupFilter", () => {
  it("offers nothing to an organization with no groups", () => {
    const { container } = render(<GroupFilter value={null} onChange={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("narrows to one group and back to every group", async () => {
    state.groups = [group("fin", "Finance"), group("sales", "Sales")];
    const onChange = vi.fn();
    const { rerender } = render(<GroupFilter value={null} onChange={onChange} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by group" }));
    await userEvent.click(screen.getByRole("option", { name: "Sales" }));
    expect(onChange).toHaveBeenLastCalledWith("sales");

    rerender(<GroupFilter value="sales" onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by group" }));
    await userEvent.click(screen.getByRole("option", { name: "Every group" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("stays while a filter is on, so it can be taken off", () => {
    render(<GroupFilter value="gone" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "Filter by group" })).toBeInTheDocument();
  });
});

describe("NothingSharedWithGroup", () => {
  it("names the group nothing was given to, and where to give it some", () => {
    state.groups = [group("fin", "Finance")];
    render(<NothingSharedWithGroup groupId="fin" />);
    expect(screen.getByText("Nothing here is shared with Finance yet")).toBeInTheDocument();
    expect(screen.getByText(/from the group's page/)).toBeInTheDocument();
  });
});
