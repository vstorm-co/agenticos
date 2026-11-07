import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceSwitcher } from "./workspace-switcher";

const ACME = {
  id: "acme",
  name: "Acme",
  is_personal: false,
  avatar_url: null,
  avatar_color: null,
};
const PERSONAL = { ...ACME, id: "personal", name: "Ada's workspace", is_personal: true };
const workspace = {
  orgs: [ACME, PERSONAL],
  activeOrg: ACME as typeof ACME | null,
  fetchOrgs: vi.fn(),
  switchOrg: vi.fn(),
};
const push = vi.fn();

vi.mock("@/hooks", () => ({ useOrganizations: () => workspace }));
vi.mock("@/lib/locale-navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/agents",
}));

beforeEach(() => {
  workspace.orgs = [ACME, PERSONAL];
  workspace.activeOrg = ACME;
  vi.clearAllMocks();
});

describe("WorkspaceSwitcher", () => {
  it("shows the current workspace before opening its menu", () => {
    render(<WorkspaceSwitcher />);

    const trigger = screen.getByRole("button", { name: "Switch workspace, current: Acme" });
    expect(within(trigger).getByText("Workspace")).toBeVisible();
    expect(within(trigger).getByText("Acme")).toBeVisible();
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("preserves the current workspace's accessible name on the collapsed rail", async () => {
    render(<WorkspaceSwitcher collapsed />);

    const trigger = screen.getByRole("button", { name: "Switch workspace, current: Acme" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    await userEvent.click(trigger);
    expect(await screen.findByRole("menuitem", { name: "Acme" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("menuitem", { name: /Ada's workspace/ })).toBeInTheDocument();
  });

  it("can be opened, navigated and selected entirely with the keyboard", async () => {
    const user = userEvent.setup();
    render(<WorkspaceSwitcher />);

    await user.tab();
    expect(screen.getByRole("button", { name: "Switch workspace, current: Acme" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("menuitem", { name: "Acme" })).toHaveFocus();
    await user.keyboard("{ArrowDown}{Enter}");

    expect(workspace.switchOrg).toHaveBeenCalledWith(PERSONAL.id);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("does not guess a current workspace while selection is unresolved", async () => {
    workspace.activeOrg = null;
    render(<WorkspaceSwitcher />);

    const trigger = screen.getByRole("button", { name: "Select workspace" });
    expect(trigger).not.toHaveTextContent(ACME.name);
    await userEvent.click(trigger);
    expect(await screen.findByRole("menuitem", { name: "Acme" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("keeps workspace management available when there are no memberships", async () => {
    workspace.orgs = [];
    workspace.activeOrg = null;
    render(<WorkspaceSwitcher />);

    await userEvent.click(screen.getByRole("button", { name: "Select workspace" }));

    expect(await screen.findByRole("menuitem", { name: "Manage organizations" })).toBeVisible();
    expect(screen.getByRole("menuitem", { name: "New organization" })).toBeVisible();
  });

  it.each([
    ["Ada's workspace", undefined],
    ["Manage organizations", "/orgs"],
    ["New organization", "/orgs?create=1"],
  ])("closes a containing mobile drawer after choosing %s", async (name, destination) => {
    const onNavigate = vi.fn();
    render(<WorkspaceSwitcher onNavigate={onNavigate} />);

    await userEvent.click(screen.getByRole("button", { name: "Switch workspace, current: Acme" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: new RegExp(name) }));

    expect(onNavigate).toHaveBeenCalledOnce();
    if (destination) expect(push).toHaveBeenCalledWith(destination);
    else expect(workspace.switchOrg).toHaveBeenCalledWith(PERSONAL.id);
  });
});
