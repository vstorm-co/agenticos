import { renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
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
vi.mock("./use-members", () => ({
  useMembers: () => ({ members: [], isLoading: false, error: null }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: (select: (state: { activeOrgId: string }) => unknown) =>
    select({ activeOrgId: "org" }),
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
