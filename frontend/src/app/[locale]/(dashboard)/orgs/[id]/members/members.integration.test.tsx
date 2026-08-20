import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MembersPage from "./page";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores";
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
async function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <Suspense>{children}</Suspense>
    </QueryClientProvider>
  );
  await act(async () => {
    render(<MembersPage params={Promise.resolve({ id: "org-1" })} />, { wrapper });
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

  it("shows a peer Admin's role as a label, because it cannot be one of the options", async () => {
    serve("admin");
    await mount();

    const row = await roleCell("peer@acme.test");

    await waitFor(() => expect(within(row).queryByRole("combobox")).toBeNull());
    expect(within(row).getByText("admin")).toBeVisible();
  });

  it("lets an Owner change a peer Admin, whose role they do outrank", async () => {
    serve("owner");
    await mount();

    const row = await roleCell("peer@acme.test");

    await waitFor(() => expect(within(row).getByRole("combobox")).toBeVisible());
  });
});
