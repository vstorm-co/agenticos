import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { User } from "@/types";

import { SidebarUser } from "./sidebar-user";

const currentUser = vi.fn<() => User | null>();

const OWNER: User = {
  id: "u-1",
  email: "owner@example.com",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks", () => ({ useAuth: () => ({ user: currentUser(), logout: vi.fn() }) }));
vi.mock("@/stores", () => ({
  useAuthStore: <T,>(selector: (state: { avatarVersion: number }) => T): T =>
    selector({ avatarVersion: 0 }),
}));

/**
 * jsdom cannot open a Radix menu — it has no layout and no real pointer events —
 * so what the menu offers is left to `e2e/auth.spec.ts`, which signs out for
 * real. What is asserted here is everything the closed trigger has to get
 * right, which is most of why this block moved out of the top bar.
 */
describe("SidebarUser", () => {
  it("says which account is signed in without being opened", () => {
    // On a platform where the account decides what every request is allowed to
    // do, "who am I" should not cost a click.
    currentUser.mockReturnValue({ ...OWNER, full_name: "Ada Owner" });

    render(<SidebarUser />);

    const trigger = screen.getByRole("button");
    expect(trigger).toHaveTextContent("Ada Owner");
    expect(trigger).toHaveTextContent("owner@example.com");
  });

  it("falls back to the local part of the address when there is no name", () => {
    currentUser.mockReturnValue(OWNER);

    render(<SidebarUser />);

    expect(screen.getByRole("button")).toHaveTextContent("owner");
  });

  it("is a menu, and says so before it is opened", () => {
    // The only affordance a keyboard user has: focus the button, read that it
    // opens a menu, press Enter.
    currentUser.mockReturnValue(OWNER);

    render(<SidebarUser />);

    expect(screen.getByRole("button")).toHaveAttribute("aria-haspopup", "menu");
  });

  it("renders nothing while the session is still being checked", () => {
    // `AuthGuard` holds the page back until /auth/me answers, so a missing user
    // is that moment — not a signed-out visitor to offer a login button to. An
    // avatar with no account behind it would be worse than an empty corner.
    currentUser.mockReturnValue(null);

    const { container } = render(<SidebarUser />);

    expect(container).toBeEmptyDOMElement();
  });
});
