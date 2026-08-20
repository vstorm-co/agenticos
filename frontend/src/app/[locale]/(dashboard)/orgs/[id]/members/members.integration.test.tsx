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
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => path(),
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

const ME = "user-me";

function member(id: string, email: string, role: string) {
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
  };
}

/** Answer every request the page makes, as a caller holding `role`. */
function serve(role: string) {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === "/roles/catalog") return Promise.resolve(ROLE_CATALOG);
    if (url.startsWith("/me/permissions")) return Promise.resolve(permissionsOf(role));
    if (url === "/orgs")
      return Promise.resolve({
        items: [{ id: "org-1", name: "Acme", avatar_color: null }],
        total: 1,
      });
    if (url.endsWith("/members")) {
      return Promise.resolve({
        items: [
          member(ME, "me@acme.test", role),
          member("user-peer", "peer@acme.test", "admin"),
          member("user-builder", "builder@acme.test", "builder"),
          member("user-owner", "owner@acme.test", "owner"),
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
  await act(async () => {
    render(<MembersPage params={Promise.resolve({ id: orgId })} />, { wrapper });
  });
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

  it("keeps a peer Admin demotable, showing the role it cannot re-assign", async () => {
    // `change_role` judges the role being handed out, not the one being
    // replaced, so an Admin may demote a peer Admin to Builder - and a control
    // that offered no way to would remove a supported action. The current role
    // is in the list so the trigger is not blank, and disabled because
    // assigning it is the part they may not do.
    serve("admin");
    await mount();

    const row = await roleCell("peer@acme.test");
    await waitFor(() => expect(within(row).getByRole("combobox")).toHaveTextContent("admin"));

    await userEvent.click(within(row).getByRole("combobox"));

    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.textContent?.trim())).toEqual([
      "admin",
      "builder",
      "operator",
      "member",
      "viewer",
    ]);
    expect(options[0]).toHaveAttribute("data-disabled");
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
      if (url.endsWith("/members"))
        return Promise.resolve({
          items: [
            member(ME, "me@acme.test", "owner"),
            member("user-peer", "peer@acme.test", "admin"),
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
      if (url.endsWith("/members"))
        return Promise.resolve({ items: [member(ME, "me@acme.test", "admin")], total: 1 });
      return Promise.resolve({ items: [], total: 0 });
    });
    await mount();

    expect(await screen.findByText(/role list could not be loaded/i)).toBeVisible();
  });

  it("lets an Owner change a peer Admin, whose role they do outrank", async () => {
    serve("owner");
    await mount();

    const row = await roleCell("peer@acme.test");

    await waitFor(() => expect(within(row).getByRole("combobox")).toBeVisible());
  });
});
