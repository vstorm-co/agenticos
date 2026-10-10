import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import GroupsPage from "./page";
import GroupPage from "./[id]/page";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
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
      raw: vi.fn(),
    },
  };
});
const saveBlob = vi.hoisted(() => vi.fn());
vi.mock("@/lib/file-access", () => ({ saveBlob }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/groups",
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

const FINANCE = {
  id: "g-fin",
  organization_id: "org-1",
  name: "Finance",
  description: "Invoices and budgets",
  icon: "banknote",
  monthly_budget_usd: "50.000000" as string | null,
  member_count: 2,
  created_at: "2026-10-01T00:00:00Z",
};

let shared: unknown[];

/** The test catalog's roles, plus `runs:view` where a test reads spend. */
function serve(role: string, { seesSpend = false } = {}) {
  const granted = permissionsOf(role);
  if (seesSpend)
    granted.permissions = [...granted.permissions, { permission: "runs:view", scope: "all" }];
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === "/roles/catalog") return Promise.resolve(ROLE_CATALOG);
    if (url.startsWith("/me/permissions")) return Promise.resolve(granted);
    if (url === "/orgs/org-1/groups") return Promise.resolve({ items: [FINANCE], total: 1 });
    if (url === "/orgs/org-1/groups/spend")
      return Promise.resolve({
        since: "2026-10-01T00:00:00Z",
        items: [{ group_id: "g-fin", spent_usd: "41.500000", run_count: 12 }],
      });
    if (url === "/orgs/org-1/groups/g-fin/resources")
      return Promise.resolve({ items: shared, total: shared.length });
    return Promise.resolve({ items: [], total: 0 });
  });
}

async function mount(page: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <Suspense>{page}</Suspense>
      </QueryClientProvider>,
    );
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: "org-1", refusedOrgIds: [] });
  shared = [];
});

describe("the groups page", () => {
  it("lists the departments, each opening its own page", async () => {
    serve("viewer");
    await mount(<GroupsPage />);

    const link = await screen.findByRole("link", { name: "Finance" });
    expect(link).toHaveAttribute("href", "/groups/g-fin");
    expect(screen.queryByRole("button", { name: "Add departments" })).toBeNull();
  });

  it("adds departments from the templates for somebody who manages members", async () => {
    serve("owner");
    vi.mocked(apiClient.post).mockResolvedValue(FINANCE);
    await mount(<GroupsPage />);

    await userEvent.click(await screen.findByRole("button", { name: "Add departments" }));
    await userEvent.click(screen.getByRole("button", { name: /Add 5 departments/ }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(5));
    expect(apiClient.post).toHaveBeenCalledWith("/orgs/org-1/groups", {
      name: "Sales",
      description: "Customers, deals and the pipeline.",
      icon: "briefcase",
    });
  });

  it("opens the forms and the members from the list", async () => {
    serve("owner");
    await mount(<GroupsPage />);

    await userEvent.click(await screen.findByRole("button", { name: "New group" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await userEvent.click(screen.getByRole("button", { name: "Members of Finance" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("gives a new group a mark, and takes it back on a second click", async () => {
    serve("owner");
    vi.mocked(apiClient.post).mockResolvedValue(FINANCE);
    await mount(<GroupsPage />);

    await userEvent.click(await screen.findByRole("button", { name: "New group" }));
    await userEvent.type(screen.getByLabelText("Name"), "Legal");
    await userEvent.click(screen.getByRole("radio", { name: "Money" }));
    await userEvent.click(screen.getByRole("radio", { name: "Scales" }));
    await userEvent.click(screen.getByRole("radio", { name: "Scales" }));
    await userEvent.click(screen.getByRole("radio", { name: "Scales" }));
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/orgs/org-1/groups", {
        name: "Legal",
        description: null,
        icon: "scale",
        monthly_budget_usd: null,
      }),
    );
  });

  it("caps a department's month, and lifts the cap when the box is emptied (#2072)", async () => {
    serve("owner");
    vi.mocked(apiClient.patch).mockResolvedValue(FINANCE);
    await mount(<GroupPage params={Promise.resolve({ id: "g-fin" })} />);

    await userEvent.click(await screen.findByRole("button", { name: "Edit group" }));
    const budget = screen.getByLabelText("Monthly budget (USD)");
    expect(budget).toHaveValue(50);
    await userEvent.clear(budget);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(
        "/orgs/org-1/groups/g-fin",
        expect.objectContaining({ monthly_budget_usd: null }),
      ),
    );

    await userEvent.click(await screen.findByRole("button", { name: "Edit group" }));
    await userEvent.clear(screen.getByLabelText("Monthly budget (USD)"));
    await userEvent.type(screen.getByLabelText("Monthly budget (USD)"), "80");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenLastCalledWith(
        "/orgs/org-1/groups/g-fin",
        expect.objectContaining({ monthly_budget_usd: 80 }),
      ),
    );
  });
});

describe("one group's page", () => {
  it("shows what was shared with the department, by kind", async () => {
    serve("viewer");
    shared = [
      { kind: "skill", id: "s1", name: "month-end-close", level: "use" },
      { kind: "agent", id: "a1", name: "Accounts payable", level: "read" },
    ];
    await mount(<GroupPage params={Promise.resolve({ id: "g-fin" })} />);

    expect(await screen.findByRole("link", { name: "month-end-close" })).toHaveAttribute(
      "href",
      "/skills",
    );
    expect(screen.getByRole("link", { name: "Accounts payable" })).toHaveAttribute(
      "href",
      "/agents/a1",
    );
    expect(screen.getByText("can use")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit group" })).toBeNull();
  });

  it("says how to give a department something when it has nothing", async () => {
    serve("owner");
    await mount(<GroupPage params={Promise.resolve({ id: "g-fin" })} />);

    expect(await screen.findByText("Nothing is shared with Finance yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit group" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "2 members" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("shows the month against the cap and exports it, for someone who sees spend (#2072)", async () => {
    serve("owner", { seesSpend: true });
    vi.mocked(apiClient.raw).mockResolvedValue(new Response("member,agent,runs,cost_usd"));
    await mount(<GroupPage params={Promise.resolve({ id: "g-fin" })} />);

    expect(await screen.findByText("$41.50")).toBeInTheDocument();
    expect(screen.getByText("of the $50.00 monthly cap - $8.50 left")).toBeInTheDocument();
    expect(screen.getByText("12 runs")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await waitFor(() =>
      expect(saveBlob).toHaveBeenCalledWith(expect.anything(), "Finance-spend.csv"),
    );
  });

  it("says a department without a cap has none, and a failed export says why", async () => {
    FINANCE.monthly_budget_usd = null;
    serve("owner", { seesSpend: true });
    vi.mocked(apiClient.raw).mockRejectedValue(new Error("boom"));
    await mount(<GroupPage params={Promise.resolve({ id: "g-fin" })} />);

    expect(await screen.findByText("spent this month - no monthly cap")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(saveBlob).not.toHaveBeenCalled();
    FINANCE.monthly_budget_usd = "50.000000";
  });

  it("says when the group is not one of this organization's", async () => {
    serve("viewer");
    await mount(<GroupPage params={Promise.resolve({ id: "g-gone" })} />);

    expect(await screen.findByText("Group not found")).toBeInTheDocument();
  });
});
