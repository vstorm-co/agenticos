import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationMenuItems } from "./org-switcher";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useOrgStore } from "@/stores";

/**
 * Switching organization from a page that names one in its URL.
 *
 * The URL decides the tenant (#1032), so a switch that only set the id left the
 * page acting on the organization just left - and the guard, which adopts what
 * the path names, wrote the id straight back. The switch takes the route with
 * it, which is what makes it a switch rather than a flicker.
 */

const ACME = "11111111-1111-1111-1111-111111111111";
const GLOBEX = "22222222-2222-2222-2222-222222222222";

const push = vi.fn();
const fetchOrgs = vi.fn();
const switchOrg = vi.fn((id: string) => useOrgStore.getState().setActiveOrgId(id));
let pathname = "/agents";
const organizations = [
  { id: ACME, name: "Acme", is_personal: false, avatar_url: null, avatar_color: null },
  { id: GLOBEX, name: "Globex", is_personal: false, avatar_url: null, avatar_color: null },
] as const;
let activeOrg: (typeof organizations)[number] | null = organizations[0];

vi.mock("@/lib/locale-navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => pathname,
}));

vi.mock("@/hooks", () => ({
  useOrganizations: () => ({
    orgs: organizations,
    activeOrg,
    fetchOrgs,
    switchOrg,
  }),
}));

/**
 * The shared items own tenant switching and navigation; the sidebar's trigger
 * has its own interaction tests.
 */
function mount(onNavigate?: () => void) {
  render(
    <NextIntlClientProvider locale="en" messages={{}}>
      <DropdownMenu open>
        <DropdownMenuTrigger>open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <OrganizationMenuItems onNavigate={onNavigate} />
        </DropdownMenuContent>
      </DropdownMenu>
    </NextIntlClientProvider>,
  );
}

async function choose(name: string) {
  await userEvent.click(await screen.findByText(name));
}

beforeEach(() => {
  push.mockClear();
  switchOrg.mockClear();
  fetchOrgs.mockClear();
  activeOrg = organizations[0];
  pathname = "/agents";
  useOrgStore.setState({ activeOrgId: ACME, refusedOrgIds: [] });
});

describe("OrganizationMenuItems", () => {
  it("takes an organization-scoped page to the same page for the one picked", async () => {
    pathname = `/orgs/${ACME}/members`;
    mount();

    await choose("Globex");

    expect(useOrgStore.getState().activeOrgId).toBe(GLOBEX);
    expect(push).toHaveBeenCalledWith(`/orgs/${GLOBEX}/members`);
  });

  it("keeps the sub-page, so the roles page switches to the roles page", async () => {
    pathname = `/orgs/${ACME}/roles`;
    mount();

    await choose("Globex");

    expect(push).toHaveBeenCalledWith(`/orgs/${GLOBEX}/roles`);
  });

  it("stays put on a page that belongs to no organization in particular", async () => {
    // Every other route is tenant-agnostic: the switch changes what they show,
    // not which of them is open.
    pathname = "/agents";
    mount();

    await choose("Globex");

    expect(useOrgStore.getState().activeOrgId).toBe(GLOBEX);
    expect(push).not.toHaveBeenCalled();
  });

  it("switches the organization overview without adding a sub-page", async () => {
    pathname = `/orgs/${ACME}`;
    mount();

    await choose("Globex");

    expect(push).toHaveBeenCalledWith(`/orgs/${GLOBEX}`);
  });

  it("marks only the actual current organization", async () => {
    activeOrg = organizations[1];
    mount();

    expect(await screen.findByRole("menuitem", { name: "Globex" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("menuitem", { name: "Acme" })).not.toHaveAttribute("aria-current");
  });

  it("does not present the first organization as current before one is selected", async () => {
    activeOrg = null;
    mount();

    expect(await screen.findByRole("menuitem", { name: "Acme" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByRole("menuitem", { name: "Globex" })).not.toHaveAttribute("aria-current");
  });

  it("dismisses the drawer after switching organization", async () => {
    const onNavigate = vi.fn();
    mount(onNavigate);

    await choose("Globex");

    expect(useOrgStore.getState().activeOrgId).toBe(GLOBEX);
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it("closes the drawer without reloading the current organization", async () => {
    pathname = `/orgs/${ACME}/members`;
    const onNavigate = vi.fn();
    mount(onNavigate);

    await choose("Acme");

    expect(switchOrg).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it("rewrites another organization's path when choosing the active organization", async () => {
    pathname = `/orgs/${GLOBEX}/members`;
    const onNavigate = vi.fn();
    mount(onNavigate);

    await choose("Acme");

    expect(switchOrg).not.toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith(`/orgs/${ACME}/members`);
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it("adopts the organization already named by the path without navigating again", async () => {
    pathname = `/orgs/${GLOBEX}/roles`;
    mount();

    await choose("Globex");

    expect(useOrgStore.getState().activeOrgId).toBe(GLOBEX);
    expect(push).not.toHaveBeenCalled();
  });

  it.each([
    ["Manage organizations", "/orgs"],
    ["New organization", "/orgs?create=1"],
  ])("dismisses the drawer when choosing %s", async (name, destination) => {
    const onNavigate = vi.fn();
    mount(onNavigate);

    await choose(name);

    expect(push).toHaveBeenCalledWith(destination);
    expect(switchOrg).not.toHaveBeenCalled();
    expect(onNavigate).toHaveBeenCalledOnce();
  });
});
