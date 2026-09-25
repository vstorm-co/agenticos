import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DirectoryPage from "./page";
import { ActiveOrgGuard } from "@/components/layout/active-org-guard";
import { apiClient, ApiError } from "@/lib/api-client";
import { assignableRoles } from "@/lib/assignable-roles";
import { useOrgStore } from "@/stores";
import { permissionsOf, ROLE_CATALOG } from "@/test-utils/role-catalog";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/orgs/org-1/directory",
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

const DN = "cn=finance,ou=groups,dc=acme,dc=test";
const MAPPINGS = [
  {
    id: "m-1",
    organization_id: "org-1",
    external_group: DN,
    role: "member",
    group_id: "g-fin",
    group_name: "Finance",
    created_at: "2026-09-01T00:00:00Z",
  },
  {
    id: "m-2",
    organization_id: "org-1",
    external_group: "engineering",
    role: "builder",
    group_id: null,
    group_name: null,
    created_at: "2026-09-01T00:00:00Z",
  },
  {
    id: "m-3",
    organization_id: "org-1",
    external_group: "auditors",
    role: "viewer",
    group_id: "g-gone",
    group_name: null,
    created_at: "2026-09-01T00:00:00Z",
  },
];

let mappings: unknown[];

/** Answer every request the page makes, as a caller holding `role`. */
function serve(role: string, overrides: Record<string, () => Promise<unknown>> = {}) {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    const override = overrides[url];
    if (override) return override();
    if (url === "/roles/catalog") return Promise.resolve(ROLE_CATALOG);
    if (url.startsWith("/me/permissions")) return Promise.resolve(permissionsOf(role));
    if (url === "/orgs")
      return Promise.resolve({ items: [{ id: "org-1", name: "Acme" }], total: 1 });
    if (url === "/orgs/org-1/directory-mappings")
      return Promise.resolve({ items: mappings, total: mappings.length });
    if (url === "/orgs/org-1/groups")
      return Promise.resolve({
        items: [
          {
            id: "g-fin",
            organization_id: "org-1",
            name: "Finance",
            description: null,
            member_count: 2,
            created_at: "2026-09-01T00:00:00Z",
          },
        ],
        total: 1,
      });
    return Promise.resolve({ items: [], total: 0 });
  });
}

async function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ActiveOrgGuard />
      <Suspense>{children}</Suspense>
    </QueryClientProvider>
  );
  await act(async () => {
    render(<DirectoryPage params={Promise.resolve({ id: "org-1" })} />, { wrapper });
  });
}

/** Open a Radix select and choose one of its options. */
async function choose(trigger: HTMLElement, option: string) {
  await userEvent.click(trigger);
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: "org-1", refusedOrgIds: [] });
  mappings = MAPPINGS;
});

describe("the directory mappings page", () => {
  it("lists the mappings from the server, with the rules they follow", async () => {
    serve("admin");
    await mount();

    expect(await screen.findByText(DN)).toHaveClass("font-mono");
    const finance = screen.getByText(DN).closest("tr") as HTMLElement;
    expect(within(finance).getByText("member")).toBeInTheDocument();
    expect(within(finance).getByText("Finance")).toBeInTheDocument();
    expect(
      within(screen.getByText("engineering").closest("tr") as HTMLElement).getByText("No group"),
    ).toBeInTheDocument();
    // A group the server could not name is shown by its id.
    expect(screen.getByText("g-gone")).toBeInTheDocument();
    expect(screen.getByText(/admin, builder, operator, member, viewer/)).toBeInTheDocument();
  });

  it("gives a member manager without roles:manage nothing to add or delete", async () => {
    // Adding a mapping hands a role out, which is `roles:manage` on top of reading.
    serve("admin");
    await mount();
    await screen.findByText(DN);

    expect(screen.queryByRole("button", { name: "Add mapping" })).toBeNull();
    expect(screen.queryByRole("button", { name: `Remove ${DN}` })).toBeNull();
  });

  it("tells a caller without members:manage whose page this is, and asks nothing", async () => {
    serve("builder");
    await mount();

    expect(
      await screen.findByText("Directory mappings are for member managers"),
    ).toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith("/orgs/org-1/directory-mappings");
  });

  it("says the permission check failed rather than that the caller may not look", async () => {
    serve("owner", { "/me/permissions": () => Promise.reject(new ApiError(500, "down")) });
    await mount();

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("Directory mappings are for member managers")).toBeNull();
  });

  it("offers exactly the roles the caller outranks, and posts the mapping", async () => {
    serve("owner");
    vi.mocked(apiClient.post).mockResolvedValue(MAPPINGS[0]);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add mapping" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Directory group"), " cn=ops,dc=acme ");

    await userEvent.click(within(dialog).getByLabelText("Role"));
    const offered = screen.getAllByRole("option").map((option) => option.textContent?.trim());
    expect(offered).toEqual(assignableRoles(ROLE_CATALOG, "owner"));
    expect(offered).not.toContain("owner");
    await userEvent.click(screen.getByRole("option", { name: "operator" }));
    await choose(within(dialog).getByLabelText("Group"), "Finance");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/orgs/org-1/directory-mappings", {
        external_group: "cn=ops,dc=acme",
        role: "operator",
        group_id: "g-fin",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("starts on Member and no group, the least a mapping can grant", async () => {
    serve("owner");
    vi.mocked(apiClient.post).mockResolvedValue(MAPPINGS[0]);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add mapping" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Directory group"), "staff");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/orgs/org-1/directory-mappings", {
        external_group: "staff",
        role: "member",
        group_id: null,
      }),
    );
  });

  it("puts an already-mapped group under its field", async () => {
    serve("owner");
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "That directory group is already mapped here", {
        error: { code: "ALREADY_EXISTS", message: "That directory group is already mapped here" },
      }),
    );
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add mapping" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Directory group"), "engineering");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));

    expect(
      await within(dialog).findByText("That directory group is already mapped here"),
    ).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("Directory group"), "2");
    expect(within(dialog).queryByText("That directory group is already mapped here")).toBeNull();
  });

  it("toasts a refusal no field owns, such as a role the server says is outranked", async () => {
    const { toast } = await import("sonner");
    serve("owner");
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(403, "You cannot hand out that role"));
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add mapping" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Directory group"), "staff");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("You cannot hand out that role"));
  });

  it("offers no role and sends nothing when the role catalog is unavailable", async () => {
    serve("owner", { "/roles/catalog": () => Promise.reject(new ApiError(500, "down")) });
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add mapping" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Directory group"), "staff");

    expect(within(dialog).getByLabelText("Role")).toHaveTextContent("No role you can hand out");
    expect(within(dialog).getByRole("button", { name: "Add" })).toBeDisabled();
    // Enter in the field submits the form even with the button disabled in some
    // browsers; the handler refuses to send a mapping with no role either way.
    fireEvent.submit(
      within(dialog).getByLabelText("Directory group").closest("form") as HTMLElement,
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("closes the dialog on Cancel", async () => {
    serve("owner");
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add mapping" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("deletes a mapping only after the confirmation", async () => {
    serve("owner");
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Remove engineering" }));
    expect(screen.getByText(/The people engineering placed here leave/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith("/orgs/org-1/directory-mappings/m-2"),
    );
    await waitFor(() =>
      expect(screen.queryByText(/The people engineering placed here/)).toBeNull(),
    );
  });

  it("closes the confirmation when the delete is refused", async () => {
    serve("owner");
    vi.mocked(apiClient.delete).mockRejectedValue(new ApiError(403, "Outranked"));
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Remove auditors" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByText(/The people auditors placed here/)).toBeNull());
  });

  it("offers the first mapping from the empty state, to a caller who may add one", async () => {
    mappings = [];
    serve("owner");
    await mount();

    expect(await screen.findByText("No mappings yet")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "Add mapping" });
    await userEvent.click(buttons[buttons.length - 1] as HTMLElement);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("offers no add from the empty state to a caller who may only read", async () => {
    mappings = [];
    serve("admin");
    await mount();

    expect(await screen.findByText("No mappings yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add mapping" })).toBeNull();
  });

  it("says the list failed rather than that there are no mappings", async () => {
    serve("admin", {
      "/orgs/org-1/directory-mappings": () => Promise.reject(new ApiError(502, "Bad gateway")),
    });
    await mount();

    expect(await screen.findByText("Bad gateway")).toBeInTheDocument();
    expect(screen.queryByText("No mappings yet")).toBeNull();
  });
});
