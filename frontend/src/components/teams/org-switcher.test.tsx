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
let pathname = "/agents";

vi.mock("@/lib/locale-navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => pathname,
}));

vi.mock("@/hooks", () => ({
  useOrganizations: () => ({
    orgs: [
      { id: ACME, name: "Acme", is_personal: false, avatar_url: null, avatar_color: null },
      { id: GLOBEX, name: "Globex", is_personal: false, avatar_url: null, avatar_color: null },
    ],
    activeOrg: { id: ACME, name: "Acme", is_personal: false, avatar_url: null, avatar_color: null },
    fetchOrgs: vi.fn(),
    switchOrg: (id: string) => useOrgStore.getState().setActiveOrgId(id),
  }),
}));

/**
 * The items are menu content now, so the test provides the menu. Open by
 * default: there is no trigger of its own to click any more - the account's
 * menu at the foot of the sidebar is what carries these.
 */
function mount() {
  render(
    <NextIntlClientProvider locale="en" messages={{}}>
      <DropdownMenu open>
        <DropdownMenuTrigger>open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <OrganizationMenuItems />
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
});
