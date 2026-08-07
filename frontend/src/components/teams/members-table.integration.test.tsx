import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MembersTable } from "./members-table";
import { apiClient } from "@/lib/api-client";
import type { OrganizationMember } from "@/types";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn() } };
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function member(overrides: Partial<OrganizationMember> = {}): OrganizationMember {
  return {
    id: "m1",
    organization_id: "o1",
    user_id: "u1",
    email: "dev@acme.test",
    full_name: "Dev",
    role: "member",
    joined_at: "2026-07-01T00:00:00Z",
    ...overrides,
  } as OrganizationMember;
}

describe("MembersTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({
      all_permissions: [],
      resource_permissions: [],
      roles: [
        { name: "owner", permissions: [] },
        { name: "admin", permissions: [] },
        { name: "builder", permissions: [] },
        { name: "operator", permissions: [] },
        { name: "member", permissions: [] },
        { name: "viewer", permissions: [] },
      ],
    });
  });

  it("offers every role the deployment has, not just admin and member", async () => {
    // The regression: this platform seeds six roles and the picker offered two,
    // so "builder" and "operator" - the two that exist precisely to separate
    // building an agent from running one - were unreachable from the UI.
    render(
      <MembersTable
        members={[member()]}
        currentUserId="somebody-else"
        canManage
        onRoleChange={vi.fn()}
        onRemove={vi.fn()}
      />,
      { wrapper },
    );

    await userEvent.click(await screen.findByLabelText("Role for dev@acme.test"));

    // Compared on the label each option leads with, not on a substring of the
    // whole option: the blurbs mention other roles ("everything except
    // ownership"), and a loose match would pass against a picker missing them.
    const labels = screen.getAllByRole("option").map((option) =>
      option.textContent
        ?.trim()
        .split(/(?=[A-Z])/)[0]
        ?.toLowerCase(),
    );

    expect(labels).toEqual(["admin", "builder", "operator", "member", "viewer"]);
  });

  it("never offers owner, because ownership moves by transfer", async () => {
    // Assigning it would leave two owners, or silently demote the first - the
    // backend has a transfer endpoint precisely because it is not a role edit.
    render(
      <MembersTable
        members={[member()]}
        currentUserId="somebody-else"
        canManage
        onRoleChange={vi.fn()}
        onRemove={vi.fn()}
      />,
      { wrapper },
    );

    await userEvent.click(await screen.findByLabelText("Role for dev@acme.test"));

    const labels = screen.getAllByRole("option").map((option) =>
      option.textContent
        ?.trim()
        .split(/(?=[A-Z])/)[0]
        ?.toLowerCase(),
    );

    expect(labels).not.toContain("owner");
  });

  it("keeps each role's blurb in the list and out of the trigger", async () => {
    // The blurb answers "which of these lets them build but not publish",
    // which is a question about the set. Radix draws the selected item's
    // `ItemText` in the closed trigger, so in `children` it became a second
    // line of explanation inside `h-7 w-36`, wrapped, about a role already
    // chosen.
    render(
      <MembersTable
        members={[member()]}
        currentUserId="somebody-else"
        canManage
        onRoleChange={vi.fn()}
        onRemove={vi.fn()}
      />,
      { wrapper },
    );

    const picker = await screen.findByLabelText("Role for dev@acme.test");
    expect(picker).toHaveTextContent("member");
    expect(picker).not.toHaveTextContent("Uses what is shared with them");

    await userEvent.click(picker);
    const viewer = screen.getByRole("option", { name: "viewer" });
    expect(within(viewer).getByText("Reads only")).toBeVisible();
  });

  it("shows the owner as a badge rather than a control", () => {
    render(
      <MembersTable
        members={[member({ role: "owner" })]}
        currentUserId="somebody-else"
        canManage
        onRoleChange={vi.fn()}
        onRemove={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.queryByLabelText("Role for dev@acme.test")).toBeNull();
    expect(screen.getByText("owner")).toBeInTheDocument();
  });

  it("will not let somebody change their own role", () => {
    // The way an organization ends up with nobody who can administer it.
    render(
      <MembersTable
        members={[member()]}
        currentUserId="u1"
        canManage
        onRoleChange={vi.fn()}
        onRemove={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.queryByLabelText("Role for dev@acme.test")).toBeNull();
    expect(within(screen.getByRole("table")).getByText("(you)")).toBeInTheDocument();
  });
});
