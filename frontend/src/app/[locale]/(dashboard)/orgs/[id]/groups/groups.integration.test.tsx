import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import GroupsPage from "./page";
import { ActiveOrgGuard } from "@/components/layout/active-org-guard";
import { apiClient, ApiError } from "@/lib/api-client";
import { useOrgStore } from "@/stores";
import { permissionsOf, ROLE_CATALOG } from "@/test-utils/role-catalog";

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
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/orgs/org-1/groups",
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

const FINANCE = {
  id: "g-fin",
  organization_id: "org-1",
  name: "Finance",
  description: "Everyone who approves spend",
  member_count: 2,
  created_at: "2026-09-01T00:00:00Z",
};
const OPS = { ...FINANCE, id: "g-ops", name: "Ops", description: null, member_count: 1 };

function orgMember(id: string, email: string, fullName: string | null) {
  return {
    id: `m-${id}`,
    organization_id: "org-1",
    user_id: id,
    role: "member",
    email,
    full_name: fullName,
    avatar_url: null,
    avatar_color: null,
    joined_at: "2026-09-01T00:00:00Z",
    source: "manual",
  };
}

let groups: unknown[];

const ORG_MEMBERS = [
  orgMember("u-ann", "ann@acme.test", "Ann"),
  orgMember("u-bob", "bob@acme.test", null),
  orgMember("u-cat", "cat@acme.test", "Cat"),
  orgMember("u-dan", "dan@acme.test", null),
];

/**
 * Answer every request the page makes, as a caller holding `role`, in an
 * organization of `inOrg` (everybody, unless a test narrows it).
 */
function serve(role: string, inOrg?: string[]) {
  const orgMembers = ORG_MEMBERS.filter((row) => !inOrg || inOrg.includes(row.user_id));
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === "/roles/catalog") return Promise.resolve(ROLE_CATALOG);
    if (url.startsWith("/me/permissions")) return Promise.resolve(permissionsOf(role));
    if (url === "/orgs")
      return Promise.resolve({ items: [{ id: "org-1", name: "Acme" }], total: 1 });
    if (url === "/orgs/org-1/groups")
      return Promise.resolve({ items: groups, total: groups.length });
    if (url === "/orgs/org-1/groups/g-fin/members")
      return Promise.resolve({
        items: [
          {
            user_id: "u-ann",
            email: "ann@acme.test",
            full_name: "Ann",
            source: "directory",
            created_at: "2026-09-01T00:00:00Z",
          },
          {
            user_id: "u-bob",
            email: "bob@acme.test",
            full_name: null,
            source: "manual",
            created_at: "2026-09-01T00:00:00Z",
          },
        ],
        total: 2,
      });
    if (url.startsWith("/orgs/org-1/members"))
      return Promise.resolve({ items: orgMembers, total: orgMembers.length });
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
    render(<GroupsPage params={Promise.resolve({ id: "org-1" })} />, { wrapper });
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
  groups = [FINANCE, OPS];
});

describe("the groups page", () => {
  it("lists the organization's groups from the server", async () => {
    serve("viewer");
    await mount();

    expect(await screen.findByText("Finance")).toBeInTheDocument();
    expect(screen.getByText("Everyone who approves spend")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Members of Finance" })).toHaveTextContent(
      "2 members",
    );
    expect(screen.getByRole("button", { name: "Members of Ops" })).toHaveTextContent("1 member");
    expect(screen.getByText("2 groups")).toBeInTheDocument();
  });

  it("leaves a Viewer nothing to create, rename or delete", async () => {
    serve("viewer");
    await mount();
    await screen.findByText("Finance");

    expect(screen.queryByRole("button", { name: "New group" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit Finance" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Finance" })).toBeNull();
  });

  it("still shows a Viewer who is in a group, without the controls to change it", async () => {
    // Deciding to share with a group is deciding who it reaches.
    serve("viewer");
    await mount();
    await userEvent.click(await screen.findByRole("button", { name: "Members of Finance" }));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Ann")).toBeInTheDocument();
    expect(within(dialog).getByText("bob@acme.test")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /Remove/ })).toBeNull();
    expect(within(dialog).queryByLabelText("Add a member")).toBeNull();
  });

  it("creates a group with the name typed and no description", async () => {
    serve("admin");
    vi.mocked(apiClient.post).mockResolvedValue(FINANCE);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "New group" }));
    await userEvent.type(screen.getByLabelText("Name"), "  Legal ");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/orgs/org-1/groups", {
        name: "Legal",
        description: null,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("puts a taken name under the name field, not in a toast", async () => {
    serve("admin");
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "A group with this name already exists", {
        error: { code: "ALREADY_EXISTS", message: "A group with this name already exists" },
      }),
    );
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "New group" }));
    await userEvent.type(screen.getByLabelText("Name"), "Finance");
    await userEvent.type(screen.getByLabelText("Description"), "Money people");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("A group with this name already exists")).toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledWith("/orgs/org-1/groups", {
      name: "Finance",
      description: "Money people",
    });
    // Typing again clears it, since the name it was about is gone.
    await userEvent.type(screen.getByLabelText("Name"), "!");
    expect(screen.queryByText("A group with this name already exists")).toBeNull();
  });

  it("toasts a refusal that belongs to no field", async () => {
    const { toast } = await import("sonner");
    serve("admin");
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(403, "Not allowed"));
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "New group" }));
    await userEvent.type(screen.getByLabelText("Name"), "Legal");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Not allowed"));
  });

  it("renames a group and clears its description", async () => {
    serve("admin");
    vi.mocked(apiClient.patch).mockResolvedValue(FINANCE);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Finance" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Finance");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Money");
    await userEvent.clear(screen.getByLabelText("Description"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1/groups/g-fin", {
        name: "Money",
        description: null,
      }),
    );
  });

  it("closes the form without saving on Cancel", async () => {
    serve("admin");
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Ops" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("deletes a group only after the confirmation", async () => {
    serve("admin");
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Remove Finance" }));
    expect(screen.getByText("Delete Finance?")).toBeInTheDocument();
    expect(apiClient.delete).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/orgs/org-1/groups/g-fin"));
    await waitFor(() => expect(screen.queryByText("Delete Finance?")).toBeNull());
  });

  it("closes the confirmation when the delete is refused, the refusal toasted", async () => {
    serve("admin");
    vi.mocked(apiClient.delete).mockRejectedValue(new ApiError(403, "Not allowed"));
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Remove Ops" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByText("Delete Ops?")).toBeNull());
  });

  it("lets a member manager add and remove people, marking the directory's rows", async () => {
    serve("admin");
    vi.mocked(apiClient.post).mockResolvedValue({});
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await mount();
    await userEvent.click(await screen.findByRole("button", { name: "Members of Finance" }));
    const dialog = await screen.findByRole("dialog");

    // Ann was placed by the sync, Bob by hand.
    const ann = (await within(dialog).findByText("Ann")).closest("div.rounded-md");
    expect(ann).not.toBeNull();
    expect(within(ann as HTMLElement).getByText("Directory")).toBeInTheDocument();

    // Only organization members not already in the group are offered.
    await userEvent.click(within(dialog).getByLabelText("Add a member"));
    expect(await screen.findByRole("option", { name: "Cat (cat@acme.test)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "dan@acme.test" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /ann@acme.test/ })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: "dan@acme.test" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/orgs/org-1/groups/g-fin/members", {
        user_id: "u-dan",
      }),
    );

    await userEvent.click(within(dialog).getByRole("button", { name: "Remove bob@acme.test" }));
    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith("/orgs/org-1/groups/g-fin/members/u-bob"),
    );
  });

  it("says a group has nobody in it, and offers the whole organization to add", async () => {
    serve("admin");
    await mount();
    await userEvent.click(await screen.findByRole("button", { name: "Members of Ops" }));
    const dialog = await screen.findByRole("dialog");

    expect(await within(dialog).findByText("Nobody is in this group yet.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Add" })).toBeDisabled();
    await choose(within(dialog).getByLabelText("Add a member"), "Ann (ann@acme.test)");
    expect(within(dialog).getByRole("button", { name: "Add" })).toBeEnabled();
  });

  it("says so when everybody in the organization is already in the group", async () => {
    serve("admin", ["u-ann", "u-bob"]);
    await mount();
    await userEvent.click(await screen.findByRole("button", { name: "Members of Finance" }));
    const dialog = await screen.findByRole("dialog");

    await within(dialog).findByText("Ann");
    expect(within(dialog).getByLabelText("Add a member")).toHaveTextContent(
      "Everyone is already in this group",
    );
    expect(within(dialog).getByLabelText("Add a member")).toBeDisabled();
  });

  it("says why a group's members could not be read", async () => {
    serve("viewer");
    const base = vi.mocked(apiClient.get).getMockImplementation();
    vi.mocked(apiClient.get).mockImplementation((url: string) =>
      url === "/orgs/org-1/groups/g-fin/members"
        ? Promise.reject(new ApiError(500, "Members unavailable"))
        : (base as (url: string) => Promise<unknown>)(url),
    );
    await mount();
    await userEvent.click(await screen.findByRole("button", { name: "Members of Finance" }));

    expect(await screen.findByText("Members unavailable")).toBeInTheDocument();
  });

  it("offers a member manager the first group from the empty state", async () => {
    groups = [];
    serve("admin");
    await mount();

    expect(await screen.findByText("No groups yet")).toBeInTheDocument();
    const cards = screen.getAllByRole("button", { name: "New group" });
    await userEvent.click(cards[cards.length - 1] as HTMLElement);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("offers a Viewer no create in the empty state either", async () => {
    groups = [];
    serve("viewer");
    await mount();

    expect(await screen.findByText("No groups yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New group" })).toBeNull();
  });

  it("says the list failed rather than that there are no groups", async () => {
    serve("viewer");
    const base = vi.mocked(apiClient.get).getMockImplementation();
    vi.mocked(apiClient.get).mockImplementation((url: string) =>
      url === "/orgs/org-1/groups"
        ? Promise.reject(new ApiError(502, "Bad gateway"))
        : (base as (url: string) => Promise<unknown>)(url),
    );
    await mount();

    expect(await screen.findByText("Bad gateway")).toBeInTheDocument();
    expect(screen.queryByText("No groups yet")).toBeNull();
  });
});
