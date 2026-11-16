import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationSwitcher } from "./organization-switcher";

const ACME = {
  id: "acme",
  name: "Acme",
  is_personal: false,
  avatar_url: null as string | null,
  updated_at: "2026-11-07T12:00:00Z",
  avatar_color: null,
};
const PERSONAL = { ...ACME, id: "personal", name: "Ada's organization", is_personal: true };
const organization = {
  orgs: [ACME, PERSONAL],
  activeOrg: ACME as typeof ACME | null,
  fetchOrgs: vi.fn(),
  switchOrg: vi.fn(),
};
const push = vi.fn();
const avatarSources = vi.hoisted(() => vi.fn());

// jsdom never loads avatar images; observe the image loader's requested URL.
vi.mock("@/components/ui/avatar", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/ui/avatar")>()),
  AvatarImage: ({ src }: { src?: string }) => {
    avatarSources(src);
    return null;
  },
}));

vi.mock("@/hooks", () => ({ useOrganizations: () => organization }));
vi.mock("@/lib/locale-navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/agents",
}));

beforeEach(() => {
  organization.orgs = [ACME, PERSONAL];
  organization.activeOrg = ACME;
  vi.clearAllMocks();
});

describe("OrganizationSwitcher", () => {
  it("refreshes organizations each time its menu opens", async () => {
    const user = userEvent.setup();
    render(<OrganizationSwitcher />);
    const trigger = screen.getByRole("button", { name: "Switch organization, current: Acme" });
    expect(organization.fetchOrgs).not.toHaveBeenCalled();

    await user.click(trigger);
    expect(organization.fetchOrgs).toHaveBeenCalledTimes(1);
    await user.keyboard("{Escape}");
    await user.click(trigger);
    expect(organization.fetchOrgs).toHaveBeenCalledTimes(2);
  });

  it("requests the replacement avatar without remounting the sidebar", async () => {
    organization.activeOrg = { ...ACME, avatar_url: "/uploaded/avatar" };
    const { rerender } = render(<OrganizationSwitcher />);
    expect(avatarSources).toHaveBeenCalledWith("/api/orgs/acme/avatar?v=2026-11-07T12:00:00Z");

    organization.activeOrg = {
      ...organization.activeOrg,
      updated_at: "2026-11-07T13:00:00Z",
    };
    rerender(<OrganizationSwitcher />);
    expect(avatarSources).toHaveBeenLastCalledWith("/api/orgs/acme/avatar?v=2026-11-07T13:00:00Z");
    organization.orgs = [organization.activeOrg, PERSONAL];
    avatarSources.mockClear();
    await userEvent.click(
      screen.getByRole("button", { name: "Switch organization, current: Acme" }),
    );
    expect(avatarSources).toHaveBeenCalledWith("/api/orgs/acme/avatar?v=2026-11-07T13:00:00Z");
  });

  it("shows the current organization before opening its menu", () => {
    render(<OrganizationSwitcher />);

    const trigger = screen.getByRole("button", { name: "Switch organization, current: Acme" });
    expect(within(trigger).getByText("Organization")).toBeVisible();
    expect(within(trigger).getByText("Acme")).toBeVisible();
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("preserves the current organization's accessible name on the collapsed rail", async () => {
    render(<OrganizationSwitcher collapsed />);

    const trigger = screen.getByRole("button", { name: "Switch organization, current: Acme" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    await userEvent.click(trigger);
    expect(await screen.findByRole("menuitem", { name: "Acme" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("menuitem", { name: /Ada's organization/ })).toBeInTheDocument();
  });

  it("can be opened, navigated and selected entirely with the keyboard", async () => {
    const user = userEvent.setup();
    render(<OrganizationSwitcher />);

    await user.tab();
    expect(
      screen.getByRole("button", { name: "Switch organization, current: Acme" }),
    ).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("menuitem", { name: "Acme" })).toHaveFocus();
    await user.keyboard("{ArrowDown}{Enter}");

    expect(organization.switchOrg).toHaveBeenCalledWith(PERSONAL.id);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("does not guess a current organization while selection is unresolved", async () => {
    organization.activeOrg = null;
    render(<OrganizationSwitcher />);

    const trigger = screen.getByRole("button", { name: "Select organization" });
    expect(trigger).not.toHaveTextContent(ACME.name);
    await userEvent.click(trigger);
    expect(await screen.findByRole("menuitem", { name: "Acme" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("keeps organization management available when there are no memberships", async () => {
    organization.orgs = [];
    organization.activeOrg = null;
    render(<OrganizationSwitcher />);

    await userEvent.click(screen.getByRole("button", { name: "Select organization" }));

    expect(await screen.findByRole("menuitem", { name: "Manage organizations" })).toBeVisible();
    expect(screen.getByRole("menuitem", { name: "New organization" })).toBeVisible();
  });

  it.each([
    ["Ada's organization", undefined],
    ["Manage organizations", "/orgs"],
    ["New organization", "/orgs?create=1"],
  ])("closes a containing mobile drawer after choosing %s", async (name, destination) => {
    const onNavigate = vi.fn();
    render(<OrganizationSwitcher onNavigate={onNavigate} />);

    await userEvent.click(
      screen.getByRole("button", { name: "Switch organization, current: Acme" }),
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: new RegExp(name) }));

    expect(onNavigate).toHaveBeenCalledOnce();
    if (destination) expect(push).toHaveBeenCalledWith(destination);
    else expect(organization.switchOrg).toHaveBeenCalledWith(PERSONAL.id);
  });
});
