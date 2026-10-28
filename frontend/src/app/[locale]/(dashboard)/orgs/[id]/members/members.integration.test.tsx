import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MembersPage from "./page";
import { ActiveOrgGuard } from "@/components/layout/active-org-guard";
import { apiClient } from "@/lib/api-client";
import { useAuthStore, useOrgStore } from "@/stores";
import { permissionsOf, ROLE_CATALOG } from "@/test-utils/role-catalog";
import { assignableRoles } from "@/lib/assignable-roles";
import type { MyPermissions } from "@/types/permissions";
import { Perm } from "@/types/permissions";
import type { OrgRole } from "@/types/organization";

/**
 * Which rows offer a role picker, and which offer a label instead.
 *
 * The picker used to be drawn for every row an Admin could act on and filled
 * with every role in the catalog bar `owner` - so an Admin was offered Admin,
 * and `change_role` refused it. Worse on a *peer Admin's* row: Radix draws the
 * chosen item's text in the trigger, and `admin` was not among the items, so the
 * control rendered blank (#1028).
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// The tenant is the organization in the path, so this file needs to move it.
// The rest are what `vitest.setup.ts` provides, and for its reason.
const path = vi.fn(() => "/");
const query = vi.fn(() => new URLSearchParams());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => query(),
  usePathname: () => path(),
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

const ME = "user-me";

/**
 * Whether the caller may change this row's role, as the *server* answers it.
 *
 * Derived rather than hardcoded, and derived the same way `MemberService.list`
 * derives it: the caller holds `roles:manage` and their own role strictly
 * outranks the role this member holds now. A fixture that returned `true` for
 * every row would test a server this one is not.
 */
function mayChangeRole(callerRole: string, targetRole: string): boolean {
  return assignableRoles(ROLE_CATALOG, callerRole).includes(targetRole as OrgRole);
}

function member(
  id: string,
  email: string,
  role: string,
  canChangeRole = false,
  source: "manual" | "directory" = "manual",
) {
  return {
    // `id` as well as `user_id`: the table keys its rows on it, and four rows
    // keyed `undefined` collapse into one.
    id: `membership-${id}`,
    user_id: id,
    email,
    // Not the email: the row prints the name *and* the address, so a name that
    // is the address makes every `findByText` ambiguous.
    full_name: email.split("@")[0],
    avatar_url: null,
    avatar_color: null,
    role,
    joined_at: "2026-07-01T00:00:00Z",
    // The server's own answer to whether `change_role` would accept this, so the
    // page draws a selector only where a change would land rather than one whose
    // result is a 403 toast (#700).
    can_change_role: canChangeRole,
    source,
  };
}

/** Answer every request the page makes, as a caller holding `role`. */
function serve(role: string, extraPermissions: MyPermissions["permissions"] = []) {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === "/roles/catalog") return Promise.resolve(ROLE_CATALOG);
    if (url.startsWith("/me/permissions"))
      return Promise.resolve({
        ...permissionsOf(role),
        permissions: [...permissionsOf(role).permissions, ...extraPermissions],
      });
    if (url === "/orgs")
      return Promise.resolve({
        items: [{ id: "org-1", name: "Acme", avatar_color: null }],
        total: 1,
      });
    if (url.includes("/members")) {
      return Promise.resolve({
        items: [
          member(ME, "me@acme.test", role, mayChangeRole(role, role)),
          member("user-peer", "peer@acme.test", "admin", mayChangeRole(role, "admin")),
          member(
            "user-builder",
            "builder@acme.test",
            "builder",
            mayChangeRole(role, "builder"),
            "directory",
          ),
          member("user-owner", "owner@acme.test", "owner", mayChangeRole(role, "owner")),
        ],
        total: 4,
      });
    }
    return Promise.resolve({ items: [], total: 0 });
  });
}

/**
 * `params` is a promise the page unwraps with `use`, so the first render
 * suspends - and a suspension inside a synchronous `act` never resolves. Awaited
 * here, which is what React's own warning asks for.
 */
async function mount(orgId = "org-1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      {/* Before the page, as the dashboard layout has it: the guard adopts the
          organization the path names, and it has to happen before the page's
          own requests go out (#1032). */}
      <ActiveOrgGuard />
      <Suspense>{children}</Suspense>
    </QueryClientProvider>
  );
  const params = Promise.resolve({ id: orgId });
  const result: { view?: { rerender: (ui: ReactNode) => void } } = {};
  await act(async () => {
    result.view = render(<MembersPage params={params} />, { wrapper });
  });
  return () => result.view?.rerender(<MembersPage params={params} />);
}

/** The table cell holding `email`'s role. */
async function roleCell(email: string): Promise<HTMLElement> {
  const cell = await screen.findByText(email);
  const row = cell.closest("tr");
  if (row === null) throw new Error(`no row for ${email}`);
  return row as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  query.mockImplementation(() => new URLSearchParams());
  window.history.replaceState({}, "", "/orgs/org-1/members");
  path.mockReturnValue("/orgs/org-1/members");
  useOrgStore.setState({ activeOrgId: "org-1", refusedOrgIds: [] });
  useAuthStore.setState({
    user: {
      id: ME,
      email: "me@acme.test",
      full_name: "Me",
      is_active: true,
      created_at: "2026-07-01T00:00:00Z",
    },
    isAuthenticated: true,
  });
});

describe("the members table's role control", () => {
  it("offers an Admin only the roles they outrank, on a row they may change", async () => {
    serve("admin");
    await mount();

    const row = await roleCell("builder@acme.test");
    await userEvent.click(within(row).getByRole("combobox"));

    const labels = screen.getAllByRole("option").map((option) => option.textContent?.trim());
    expect(labels).toEqual(["builder", "operator", "member", "viewer"]);
  });

  it("offers a peer Admin no control at all, because the server would refuse it", async () => {
    // This asserted the opposite until #700, on the reading that `change_role`
    // judges the role being handed out and not the one being replaced - so an
    // Admin demoting a peer Admin to Builder was a supported action a picker
    // ought to offer. It was the hole: `remove` refuses one Admin removing
    // another, and demote-then-remove took the same authority by another door.
    // The server now refuses it, so the row shows the role as a label.
    serve("admin");
    await mount();

    const row = await roleCell("peer@acme.test");

    await waitFor(() => expect(within(row).getByText("admin")).toBeVisible());
    expect(within(row).queryByRole("combobox")).toBeNull();
  });

  it("judges the organization in its URL, not whichever one is active", async () => {
    // #1032: `X-Organization-Id` names the *active* organization on every
    // request, and the organizations list opens any org's members page without
    // switching - so this page judged Acme's members by the caller's role in
    // Globex. The guard adopts the path's organization, so what the page offers
    // is what the caller may do *there*.
    //
    // The mock answers per organization, which is what makes the difference
    // visible: an Owner of the org in the URL, an Admin of the active one.
    const URL_ORG = "22222222-2222-2222-2222-222222222222";
    path.mockReturnValue(`/orgs/${URL_ORG}/members`);
    useOrgStore.setState({ activeOrgId: "org-1", refusedOrgIds: [] });
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === "/roles/catalog") return Promise.resolve(ROLE_CATALOG);
      if (url.startsWith("/me/permissions")) {
        const asked = useOrgStore.getState().activeOrgId;
        return Promise.resolve(permissionsOf(asked === URL_ORG ? "owner" : "admin"));
      }
      if (url === "/orgs")
        return Promise.resolve({
          items: [
            { id: "org-1", name: "Globex", avatar_color: null },
            { id: URL_ORG, name: "Acme", avatar_color: null },
          ],
          total: 2,
        });
      if (url.includes("/members"))
        return Promise.resolve({
          items: [
            member(ME, "me@acme.test", "owner", mayChangeRole("owner", "owner")),
            member("user-peer", "peer@acme.test", "admin", mayChangeRole("owner", "admin")),
          ],
          total: 2,
        });
      return Promise.resolve({ items: [], total: 0 });
    });

    await mount(URL_ORG);

    const row = await roleCell("peer@acme.test");
    await userEvent.click(within(row).getByRole("combobox"));

    // An Owner's five, not an Admin's four - and `admin` selectable rather than
    // the disabled placeholder an Admin would see on this row.
    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.textContent?.trim())).toEqual([
      "admin",
      "builder",
      "operator",
      "member",
      "viewer",
    ]);
    expect(options[0]).not.toHaveAttribute("data-disabled");
  });

  it("says so when the role catalog could not be read, rather than showing labels", async () => {
    // Offering nothing and being unable to answer are the same pixels and a
    // different fact.
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === "/roles/catalog") return Promise.reject(new Error("nope"));
      if (url.startsWith("/me/permissions")) return Promise.resolve(permissionsOf("admin"));
      if (url === "/orgs")
        return Promise.resolve({
          items: [{ id: "org-1", name: "Acme", avatar_color: null }],
          total: 1,
        });
      if (url.includes("/members"))
        return Promise.resolve({ items: [member(ME, "me@acme.test", "admin")], total: 1 });
      return Promise.resolve({ items: [], total: 0 });
    });
    await mount();

    expect(await screen.findByText(/role list could not be loaded/i)).toBeVisible();
  });

  it("marks a membership the directory sync maintains, beside its role", async () => {
    serve("admin");
    await mount();

    const builder = await roleCell("builder@acme.test");
    await waitFor(() => expect(within(builder).getByRole("combobox")).toBeVisible());
    const badge = within(builder).getByText("Directory");
    expect(badge.closest("[title]")).toHaveAttribute(
      "title",
      expect.stringContaining("Changing the role here takes it over"),
    );
    expect(within(await roleCell("peer@acme.test")).queryByText("Directory")).toBeNull();
  });

  it("marks it beside the plain label too, for a caller who cannot change it", async () => {
    serve("viewer");
    await mount();

    const builder = await roleCell("builder@acme.test");
    expect(within(builder).getByText("Directory")).toBeVisible();
    expect(within(builder).queryByRole("combobox")).toBeNull();
  });

  it("links to the groups for everyone, and to the directory only for a member manager", async () => {
    serve("viewer");
    await mount();

    expect(await screen.findByRole("link", { name: "Groups" })).toHaveAttribute(
      "href",
      "/orgs/org-1/groups",
    );
    expect(screen.queryByRole("link", { name: "Directory" })).toBeNull();
  });

  it("links a member manager to the directory mappings", async () => {
    serve("admin");
    await mount();

    expect(await screen.findByRole("link", { name: "Directory" })).toHaveAttribute(
      "href",
      "/orgs/org-1/directory",
    );
  });

  it("lets an Owner change a peer Admin, whose role they do outrank", async () => {
    serve("owner");
    await mount();

    const row = await roleCell("peer@acme.test");

    await waitFor(() => expect(within(row).getByRole("combobox")).toBeVisible());
  });
});

describe("organization settings tabs", () => {
  it("shows members by default and preserves a profile draft while switching tabs", async () => {
    serve("owner");
    await mount();
    expect(await screen.findByRole("tab", { name: "Members" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
    window.history.replaceState({}, "", "?tab=voice#org-voice");
    await userEvent.click(screen.getByRole("tab", { name: "Profile" }));
    expect(window.location.hash).toBe("");
    expect(screen.getByTitle("Change organization avatar")).toHaveClass("rounded-full");
    const name = screen.getByDisplayValue("Acme");
    await userEvent.clear(name);
    await userEvent.type(name, "New workspace");
    expect(new URL(window.location.href).searchParams.get("tab")).toBe("profile");
    await userEvent.click(screen.getByRole("tab", { name: "Members" }));
    expect(name).not.toBeVisible();
    expect(new URL(window.location.href).searchParams.has("tab")).toBe(false);
    await userEvent.click(screen.getByRole("tab", { name: "Profile" }));
    expect(screen.getByDisplayValue("New workspace")).toBeVisible();
  });

  it("opens a settings tab directly from its URL", async () => {
    query.mockImplementation(() => new URLSearchParams("tab=voice"));
    serve("owner", [{ permission: Perm.orgSettings, scope: "all" }]);
    await mount();
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Voice" })).toHaveAttribute("aria-selected", "true"),
    );
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
    expect(screen.getByRole("tabpanel")).toHaveAttribute("data-state", "active");
  });

  it("follows a query change without remounting the page", async () => {
    serve("viewer");
    const rerender = await mount();
    await screen.findByText("peer@acme.test");
    query.mockImplementation(() => new URLSearchParams("tab=profile"));
    rerender();
    expect(screen.getByRole("tab", { name: "Profile" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByDisplayValue("Acme")).toBeVisible();
  });

  it("shows the settings sections only with their matching grants", async () => {
    serve("owner", [
      { permission: Perm.orgSettings, scope: "all" },
      { permission: Perm.budgetsManage, scope: "all" },
      { permission: Perm.approvalsDecide, scope: "all" },
    ]);
    await mount();
    await waitFor(() =>
      expect(screen.getAllByRole("tab").map((item) => item.textContent)).toEqual([
        "Members",
        "Profile",
        "Budget and approvals",
        "Proactivity",
        "Voice",
      ]),
    );
    await userEvent.click(screen.getByRole("tab", { name: "Proactivity" }));
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Proactivity");
  });

  it.each(["voice", "governance", "proactivity", "assistant", "unknown"])(
    "falls back to members for unavailable tab %s",
    async (tab) => {
      query.mockImplementation(() => new URLSearchParams({ tab }));
      serve("viewer");
      await mount();
      await waitFor(() =>
        expect(screen.getByRole("tab", { name: "Members" })).toHaveAttribute(
          "aria-selected",
          "true",
        ),
      );
      expect(screen.getAllByRole("tab").map((item) => item.textContent)).toEqual([
        "Members",
        "Profile",
      ]);
      expect(await screen.findByText("peer@acme.test")).toBeVisible();
    },
  );
});
