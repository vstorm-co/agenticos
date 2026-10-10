import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AddToGroupDialog } from "./add-to-group-dialog";
import { GroupMembersDialog } from "@/components/orgs/group-members-dialog";
import type { Group, GroupMember, GroupResource } from "@/types/groups";

const hooks = vi.hoisted(() => ({
  members: [] as GroupMember[],
  shareable: [] as GroupResource[],
  sharing: { isLoading: false, error: null as unknown },
  add: vi.fn(),
  remove: vi.fn(),
  setLead: vi.fn(),
  share: vi.fn(),
  me: "u-lead",
}));

vi.mock("@/hooks", () => ({
  useGroupMembers: () => ({
    members: hooks.members,
    isLoading: false,
    error: null,
    add: { mutate: hooks.add, isPending: false },
    remove: { mutate: hooks.remove, isPending: false },
    setLead: { mutate: hooks.setLead, isPending: false },
  }),
  useMembers: () => ({
    members: [{ user_id: "u-new", email: "new@acme.example", full_name: "New Hire" }],
  }),
  useGroupSharing: () => ({
    shareable: hooks.shareable,
    isLoading: hooks.sharing.isLoading,
    error: hooks.sharing.error,
    share: { mutate: hooks.share, isPending: false },
  }),
}));
vi.mock("@/stores", () => ({
  useAuthStore: (select: (state: { user: { id: string } }) => unknown) =>
    select({ user: { id: hooks.me } }),
}));
vi.mock("@/components/orgs/group-member-add", () => ({
  GroupMemberAdd: ({ onAdd }: { onAdd: (id: string) => void }) => (
    <button type="button" onClick={() => onAdd("u-new")}>
      add member
    </button>
  ),
}));

const FINANCE: Group = {
  id: "g-fin",
  name: "Finance",
  description: null,
  icon: null,
  member_count: 2,
  created_at: "2026-10-10T00:00:00Z",
} as Group;

function member(overrides: Partial<GroupMember>): GroupMember {
  return {
    user_id: "u-lead",
    email: "lead@acme.example",
    full_name: "Lena Lead",
    source: "manual",
    is_lead: false,
    created_at: "2026-10-10T00:00:00Z",
    ...overrides,
  };
}

describe("a group's lead (#2072)", () => {
  it("lets the lead add and remove members without administering", async () => {
    hooks.members = [
      member({ is_lead: true }),
      member({ user_id: "u-2", email: "b@acme.example" }),
    ];
    render(<GroupMembersDialog orgId="o1" group={FINANCE} canManage={false} onClose={vi.fn()} />);

    expect(screen.getByText("Lead")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /group's lead/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "add member" }));
    expect(hooks.add).toHaveBeenCalledWith("u-new");
  });

  it("lets an administrator name and unname a lead", async () => {
    hooks.me = "u-admin";
    hooks.members = [member({ is_lead: true }), member({ user_id: "u-2", full_name: "Bo" })];
    render(<GroupMembersDialog orgId="o1" group={FINANCE} canManage onClose={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "Make Bo the group's lead" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Lena Lead no longer leads the group" }),
    );

    expect(hooks.setLead).toHaveBeenNthCalledWith(1, { userId: "u-2", isLead: true });
    expect(hooks.setLead).toHaveBeenNthCalledWith(2, { userId: "u-lead", isLead: false });
  });

  it("gives an ordinary member nothing to change", () => {
    hooks.me = "u-someone";
    hooks.members = [member({})];
    render(<GroupMembersDialog orgId="o1" group={FINANCE} canManage={false} onClose={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "add member" })).not.toBeInTheDocument();
  });
});

describe("adding to a group from its page (#2072)", () => {
  const items: GroupResource[] = [
    { kind: "skill", id: "s1", name: "Month-end close", level: "use" },
    { kind: "agent", id: "a1", name: "Payables", level: "use" },
  ];

  it("shares the ticked items at the chosen level", async () => {
    hooks.shareable = items;
    render(<AddToGroupDialog orgId="o1" group={FINANCE} onClose={vi.fn()} />);

    await userEvent.click(screen.getByLabelText("Month-end close"));
    await userEvent.click(screen.getByLabelText("Payables"));
    await userEvent.click(screen.getByLabelText("Payables"));
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "can view" }));
    await userEvent.click(screen.getByRole("button", { name: "Share 1" }));

    expect(hooks.share).toHaveBeenCalledWith(
      { items: [{ kind: "skill", id: "s1" }], level: "read" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("narrows by search, and says when nothing matches or nothing is left", async () => {
    hooks.shareable = items;
    const { unmount } = render(<AddToGroupDialog orgId="o1" group={FINANCE} onClose={vi.fn()} />);
    await userEvent.type(screen.getByRole("textbox"), "pay");
    expect(screen.queryByLabelText("Month-end close")).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox"), "zzz");
    expect(screen.getByText(/Nothing you can share matches/)).toBeInTheDocument();
    unmount();

    hooks.shareable = [];
    render(<AddToGroupDialog orgId="o1" group={FINANCE} onClose={vi.fn()} />);
    expect(screen.getByText(/everything you may edit is already here/)).toBeInTheDocument();
  });

  it("shows loading and a failure", () => {
    hooks.sharing = { isLoading: true, error: null };
    const { unmount } = render(<AddToGroupDialog orgId="o1" group={FINANCE} onClose={vi.fn()} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    unmount();

    hooks.sharing = { isLoading: false, error: new Error("boom") };
    render(<AddToGroupDialog orgId="o1" group={FINANCE} onClose={vi.fn()} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    hooks.sharing = { isLoading: false, error: null };
  });
});
