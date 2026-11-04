import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import Page from "./page";
import { avatarPalette } from "@/lib/avatar-color";
const avatars = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/avatar", () => ({
  Avatar: ({ children, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
    <span {...props}>{children}</span>
  ),
  AvatarFallback: ({ children, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
    <span {...props}>{children}</span>
  ),
  AvatarImage: ({ src }: { src: string }) => {
    avatars(src);
    return null;
  },
}));
vi.mock("@/hooks", async () => ({
  ...(await vi.importActual<typeof import("@/hooks")>("@/hooks")),
  useUrlSort: () => ({ sort: { by: "name", dir: "asc" }, setSort: vi.fn() }),
  useAdminOrganizations: () => ({
    organizations: [
      {
        id: "org-a",
        name: "Northwind Labs",
        slug: "northwind",
        is_personal: false,
        has_avatar: true,
        avatar_color: 4,
        member_count: 8,
        agent_count: 14,
        created_at: "2026-10-01T00:00:00Z",
      },
      {
        id: "org-b",
        name: "Personal",
        slug: "personal",
        is_personal: true,
        has_avatar: false,
        avatar_color: 2,
        member_count: 1,
        agent_count: 0,
        created_at: "2026-10-01T00:00:00Z",
      },
    ],
    total: 2,
    isLoading: false,
    error: null,
  }),
}));
it("shows uploaded organization portraits and colored initials without fetching missing images", () => {
  render(<Page />);
  const row = screen.getByText("Northwind Labs").closest("tr");
  expect(row).not.toBeNull();
  expect(avatars).toHaveBeenCalledWith("/api/admin/organizations/org-a/avatar");
  expect(avatars).toHaveBeenCalledTimes(1);
  expect(screen.getByText("P")).toHaveClass(avatarPalette("org-b", 2).bg);
});
