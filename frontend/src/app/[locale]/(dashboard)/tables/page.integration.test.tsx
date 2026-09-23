import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TablesPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { TableSummary } from "@/types/tables";

/**
 * The tables catalog: the list, its search, the create control's permission
 * gate, and the create dialog wired through to a real navigation. `create-table-dialog.test.tsx`
 * covers the dialog's own field behaviour; this suite proves the page renders
 * it, gates it, and reacts correctly to what it produces.
 */

let canCreate = true;
const push = vi.fn();

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/tables",
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => canCreate }) }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function table(overrides: Partial<TableSummary> = {}): TableSummary {
  return {
    id: "t-1",
    name: "Orders",
    description: "Customer orders",
    visibility: "private",
    owner_user_id: "u-1",
    schema_version: 1,
    archived_at: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: null,
    can_edit: true,
    ...overrides,
  };
}

beforeEach(() => {
  canCreate = true;
  push.mockReset();
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
});

describe("the tables catalog page", () => {
  it("lists each table with its description and visibility, linking to its detail page", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [table()], total: 1 });
    render(<TablesPage />, { wrapper });

    expect(await screen.findByText("Orders")).toBeInTheDocument();
    expect(screen.getByText("Customer orders")).toBeInTheDocument();
    expect(screen.getByText("Private")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Orders/ })).toHaveAttribute("href", "/tables/t-1");
  });

  it("shows the empty state with a create shortcut when there are no tables", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    render(<TablesPage />, { wrapper });

    expect(await screen.findByText("No tables yet")).toBeInTheDocument();
    // Two "New table" buttons exist once empty - the header action and the
    // empty state's own shortcut - so both, rather than one ambiguous query.
    expect(screen.getAllByRole("button", { name: "New table" })).toHaveLength(2);
  });

  it("shows the filtered-empty copy, not the catalog-empty one, once a search matches nothing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    render(<TablesPage />, { wrapper });
    await screen.findByText("No tables yet");

    await userEvent.type(screen.getByPlaceholderText("Search tables…"), "zzz");

    expect(await screen.findByText("No table matches")).toBeInTheDocument();
  });

  it("hides the New table control from a caller without tables:create", async () => {
    canCreate = false;
    vi.mocked(apiClient.get).mockResolvedValue({ items: [table()], total: 1 });
    render(<TablesPage />, { wrapper });

    await screen.findByText("Orders");
    // With at least one table shown, the header action is the only one that
    // could render at all - the empty-state shortcut needs an empty catalog.
    expect(screen.queryByRole("button", { name: "New table" })).not.toBeInTheDocument();
  });

  it("searches by the typed text, once debounced", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [table()], total: 1 });
    render(<TablesPage />, { wrapper });
    await screen.findByText("Orders");

    await userEvent.type(screen.getByPlaceholderText("Search tables…"), "ord");

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(
        "/tables",
        expect.objectContaining({ params: expect.objectContaining({ q: "ord" }) }),
      ),
    );
  });

  it("creates a table from the dialog and navigates to its detail page", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ ...table(), id: "t-new", name: "Invoices" });
    render(<TablesPage />, { wrapper });
    await screen.findByText("No tables yet");

    const [headerNewTable] = screen.getAllByRole("button", { name: "New table" });
    await userEvent.click(headerNewTable as HTMLElement);
    await userEvent.type(screen.getByLabelText("Name"), "Invoices");
    await userEvent.click(screen.getByRole("button", { name: "Create table" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/tables",
        expect.objectContaining({ name: "Invoices" }),
      ),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/tables/t-new"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
