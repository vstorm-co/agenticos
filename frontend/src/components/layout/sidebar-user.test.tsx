import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MAC_MAIN } from "@/components/desktop/fixtures";
import type { ShellInfo } from "@/lib/desktop/shell";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { User } from "@/types";

import { SidebarUser } from "./sidebar-user";

const desktop = vi.hoisted(() => ({ shell: null as ShellInfo | null, change: vi.fn() }));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => desktop.shell }));
vi.mock("@/hooks/use-desktop", () => ({
  useChangeServer: () => ({ mutate: desktop.change, isPending: false }),
}));
vi.mock("@/components/layout/account-preferences", () => ({
  AppearanceMenu: () => null,
  LanguageMenu: () => null,
}));
vi.mock("@/components/teams", () => ({ OrganizationMenuItems: () => null }));
beforeEach(() => {
  desktop.shell = null;
  desktop.change.mockClear();
});

const currentUser = vi.fn<() => User | null>();

const OWNER: User = {
  id: "u-1",
  email: "owner@example.com",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

vi.mock("next-intl", async () => ({
  useTranslations: (await import("@/test-utils/intl")).keyTranslations(),
}));
vi.mock("@/hooks", () => ({ useAuth: () => ({ user: currentUser(), logout: vi.fn() }) }));
vi.mock("@/stores", () => ({
  useAuthStore: <T,>(selector: (state: { avatarVersion: number }) => T): T =>
    selector({ avatarVersion: 0 }),
}));

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
    // is that moment - not a signed-out visitor to offer a login button to. An
    // avatar with no account behind it would be worse than an empty corner.
    currentUser.mockReturnValue(null);

    const { container } = render(<SidebarUser />);

    expect(container).toBeEmptyDOMElement();
  });
});

it.each([false, true])(
  "shows server switching only after opening the account menu (compact: %s)",
  async (compact) => {
    desktop.shell = MAC_MAIN;
    currentUser.mockReturnValue({ ...OWNER, full_name: "Ada Owner" });
    render(<SidebarUser compact={compact} />);
    expect(screen.queryByText("change")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(await screen.findByRole("menuitem", { name: "change" }));
    expect(desktop.change).toHaveBeenCalledOnce();
  },
);
