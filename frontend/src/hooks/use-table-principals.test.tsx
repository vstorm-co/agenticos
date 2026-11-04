import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useTablePrincipals } from "./use-table-principals";
import { useAgents } from "./use-agents";
vi.mock("./use-agents", () => ({
  useAgents: vi.fn(() => ({
    agents: [
      {
        id: "archived",
        name: "Former writer",
        slug: "writer",
        status: "archived",
        avatar_color: "violet",
        has_avatar: true,
      },
    ],
    isLoading: false,
    error: null,
  })),
}));
const directory = vi.hoisted(() => ({
  org: "org" as string | null,
  members: [
    { user_id: "anna", full_name: "Anna", email: "anna@example.test" },
    { user_id: "jan", full_name: null, email: "jan@example.test" },
  ],
  error: null as Error | null,
  loading: false,
}));
vi.mock("./use-members", () => ({
  useMembers: () => ({
    members: directory.members,
    isLoading: directory.loading,
    error: directory.error,
  }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: (select: (state: { activeOrgId: string | null }) => unknown) =>
    select({ activeOrgId: directory.org }),
}));
it("resolves an archived agent's existing identity and avatar", () => {
  const { result } = renderHook(() => useTablePrincipals("agent"));
  expect(useAgents).toHaveBeenCalledWith({ includeArchived: true, enabled: true });
  expect(result.current.items[0]).toMatchObject({
    id: "archived",
    name: "Former writer",
    archived: true,
    has_avatar: true,
  });
});

beforeEach(() => {
  directory.org = "org";
  directory.error = null;
  directory.loading = false;
});
it("resolves organization members by name with an email fallback", () => {
  const { result, rerender } = renderHook(() => useTablePrincipals("user"));
  expect(result.current.items.map((item) => item.name)).toEqual(["Anna", "jan@example.test"]);
  directory.error = new Error("Unavailable");
  directory.loading = true;
  rerender();
  expect(result.current.error).toBe(directory.error);
  expect(result.current.isLoading).toBe(true);
});
it("disables the agent directory when no organization is selected", () => {
  directory.org = null;
  renderHook(() => useTablePrincipals("agent"));
  expect(useAgents).toHaveBeenLastCalledWith({ includeArchived: true, enabled: false });
  renderHook(() => useTablePrincipals("user"));
  expect(useAgents).toHaveBeenLastCalledWith({ includeArchived: true, enabled: false });
});
