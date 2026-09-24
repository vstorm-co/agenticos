import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TableDetailPage from "./page";
import { apiClient } from "@/lib/api-client";
import { PAGE_SIZE } from "@/components/ui";
import type { RecordRead, TableRead, TableViewList } from "@/types/tables";

/**
 * The table detail page: tab/URL wiring, the `can_edit` gate on the columns
 * and view-management controls, and the kanban tab's "no grouped view yet"
 * refusal. Each view (grid, kanban, list), the schema editor, the record
 * sheet and the sharing panel all have their own suites, so they are stubbed
 * here - this page's own job is composing and gating them correctly, per
 * `.claude/rules/frontend.md`'s "prove a gated control is absent, not
 * disabled".
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), put: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

let params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => params,
  usePathname: () => "/tables/t1",
}));

vi.mock("@/components/tables/table-grid-view", () => ({
  TableGridView: ({
    columns,
    sort,
    onSort,
    onOpenRecord,
  }: {
    columns: { id: string }[];
    sort: { by: string; direction: string };
    onSort: (sort: { by: string; direction: string }) => void;
    onOpenRecord: (r: RecordRead) => void;
  }) => (
    <div
      data-testid="grid-view"
      data-column-ids={columns.map((c) => c.id).join(",")}
      data-sort={`${sort.by}:${sort.direction}`}
    >
      <button onClick={() => onOpenRecord({ ...RECORD })}>open-record-from-grid</button>
      <button onClick={() => onSort({ by: "name", direction: "desc" })}>resort-by-name</button>
    </div>
  ),
}));
vi.mock("@/components/tables/table-list-view", () => ({
  TableListView: () => <div data-testid="list-view" />,
}));
vi.mock("@/components/tables/table-kanban-view", () => ({
  TableKanbanView: ({ groupByColumnId }: { groupByColumnId: string }) => (
    <div data-testid="kanban-view" data-group-by={groupByColumnId} />
  ),
}));
vi.mock("@/components/tables/schema-editor-dialog", () => ({
  SchemaEditorDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog" aria-label="schema-dialog" /> : null,
}));
interface SheetStubProps {
  record: RecordRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRecordUpdated: (record: RecordRead) => void;
}
/** The props the page last rendered the sheet with - reachable after it closes. */
let sheetProps: SheetStubProps | null = null;
vi.mock("@/components/tables/record-detail-sheet", () => ({
  RecordDetailSheet: (props: SheetStubProps) => {
    sheetProps = props;
    return props.open ? (
      <div
        role="dialog"
        aria-label="record-sheet"
        data-record-id={props.record?.id}
        data-revision={props.record?.revision}
      />
    ) : null;
  },
}));
vi.mock("@/components/sharing/sharing-panel", () => ({
  SharingPanel: ({
    resourceType,
    resourceId,
    canManage,
  }: {
    resourceType: string;
    resourceId: string;
    canManage: boolean;
  }) => (
    <div
      data-testid="sharing-panel"
      data-resource={`${resourceType}:${resourceId}`}
      data-can-manage={String(canManage)}
    />
  ),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>{children}</Suspense>
    </QueryClientProvider>
  );
}

const RECORD: RecordRead = {
  id: "r1",
  table_id: "t1",
  external_id: null,
  schema_version: 1,
  values: { c1: "Ada" },
  revision: 1,
  created_at: "2026-09-01T00:00:00Z",
};

function table(overrides: Partial<TableRead> = {}): TableRead {
  return {
    id: "t1",
    name: "Orders",
    description: "Customer orders",
    visibility: "team",
    owner_user_id: "u1",
    schema_version: 1,
    archived_at: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: null,
    can_edit: true,
    columns: [
      {
        id: "c1",
        label: "Customer",
        type: "text",
        nullable: true,
        default: null,
        options: [],
        archived: false,
      },
      {
        id: "c2",
        label: "Status",
        type: "single_select",
        nullable: true,
        default: null,
        options: [{ id: "o1", label: "Open", archived: false }],
        archived: false,
      },
      {
        id: "c3",
        label: "Retired",
        type: "text",
        nullable: true,
        default: null,
        options: [],
        archived: true,
      },
    ],
    ...overrides,
  };
}

const emptyConfig = {
  filters: [],
  sort: { by: "created_at", direction: "asc" as const },
  visible_columns: null,
  group_by: null,
};

function views(overrides: Partial<TableViewList> = {}): TableViewList {
  return {
    items: [
      {
        id: "v-kanban",
        table_id: "t1",
        owner_user_id: "u1",
        name: "By status",
        kind: "kanban",
        visibility: "private",
        config: { ...emptyConfig, group_by: "c2" },
        can_manage: true,
        created_at: "2026-08-01T00:00:00Z",
        updated_at: null,
      },
      {
        id: "v-table",
        table_id: "t1",
        owner_user_id: "u1",
        name: "By customer",
        kind: "table",
        visibility: "private",
        config: { ...emptyConfig, sort: { by: "c1", direction: "desc" } },
        can_manage: true,
        created_at: "2026-08-01T00:00:00Z",
        updated_at: null,
      },
    ],
    total: 2,
    ...overrides,
  };
}

/** Arrive at the page with this query string, as a pasted link would. */
function arriveAt(query: string) {
  params = new URLSearchParams(query);
  window.history.replaceState({}, "", `/tables/t1${query ? `?${query}` : ""}`);
}

function serve({
  tableFixture = table(),
  viewsFixture = views(),
}: { tableFixture?: TableRead; viewsFixture?: TableViewList } = {}) {
  vi.mocked(apiClient.get).mockImplementation((path: string) => {
    if (path === "/tables/t1") return Promise.resolve(tableFixture);
    if (path === "/tables/t1/views") return Promise.resolve(viewsFixture);
    if (path === "/tables/t1/records/r1") return Promise.resolve({ ...RECORD, revision: 2 });
    return Promise.resolve({ items: [], total: 0 });
  });
  vi.mocked(apiClient.post).mockImplementation((path: string) => {
    if (path === "/tables/t1/records/query")
      return Promise.resolve({ items: [RECORD], has_more: false });
    return Promise.resolve({});
  });
}

const PARAMS = Promise.resolve({ id: "t1" });

function renderPage() {
  return render(<TableDetailPage params={PARAMS} />, { wrapper });
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
  arriveAt("");
});

describe("the table detail page", () => {
  it("shows a loading state before the table arrives", async () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));

    // `use(params)` suspends the page for one microtask before the table
    // query's own `isLoading` placeholder can mount; flushing it inside `act`
    // (rather than polling with `findByRole`) is what lets React's Suspense
    // retry - which fires outside of Testing Library's own act tracking -
    // land before the assertion.
    await act(async () => {
      renderPage();
    });

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows an error state when the table fails to load", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("boom"));
    renderPage();

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
  });

  it("shows the table's name, description and visibility", async () => {
    serve();
    renderPage();

    expect(await screen.findByText("Orders")).toBeInTheDocument();
    expect(screen.getByText("Customer orders")).toBeInTheDocument();
    expect(screen.getByText("Team")).toBeInTheDocument();
  });

  it("shows the grid view by default, with archived columns filtered out", async () => {
    serve();
    renderPage();

    const grid = await screen.findByTestId("grid-view");
    expect(grid).toHaveAttribute("data-column-ids", "c1,c2");
  });

  it("seeds the grid's sort from the active view, then still honours a header click", async () => {
    // The regression this guards: `effectiveSort` used to read straight from
    // the active view's stored config, so clicking a sortable header updated
    // state nothing downstream ever looked at again - a saved view made
    // every column header a dead click.
    serve();
    arriveAt("viewId=v-table");
    const user = userEvent.setup();
    renderPage();

    const grid = await screen.findByTestId("grid-view");
    expect(grid).toHaveAttribute("data-sort", "c1:desc");

    await user.click(screen.getByRole("button", { name: "resort-by-name" }));

    await waitFor(() =>
      expect(screen.getByTestId("grid-view")).toHaveAttribute("data-sort", "name:desc"),
    );
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/tables/t1/records/query",
        expect.objectContaining({ sort: { by: "name", direction: "desc" } }),
      ),
    );
  });

  it("re-seeds the grid's sort when switching to a different saved view", async () => {
    serve();
    arriveAt("viewId=v-table");
    const user = userEvent.setup();
    renderPage();
    const grid = await screen.findByTestId("grid-view");
    expect(grid).toHaveAttribute("data-sort", "c1:desc");

    // Override it with a header click, then switch away to the unsaved
    // view - the override must not leak into the next view's own sort.
    await user.click(screen.getByRole("button", { name: "resort-by-name" }));
    await waitFor(() => expect(grid).toHaveAttribute("data-sort", "name:desc"));

    await user.click(screen.getByRole("combobox", { name: /select a table view/i }));
    await user.click(screen.getByRole("option", { name: "Unsaved view" }));

    await waitFor(() => expect(grid).toHaveAttribute("data-sort", "created_at:asc"));
  });

  it("shows the Columns control and lets an editor open the schema dialog", async () => {
    serve();
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");

    await user.click(screen.getByRole("button", { name: /columns/i }));

    expect(screen.getByRole("dialog", { name: "schema-dialog" })).toBeInTheDocument();
  });

  it("hides the Columns control and the schema dialog entirely for a viewer without can_edit", async () => {
    serve({ tableFixture: table({ can_edit: false }) });
    renderPage();
    await screen.findByTestId("grid-view");

    expect(screen.queryByRole("button", { name: /columns/i })).not.toBeInTheDocument();
    // Absent, not merely unopened - there is no dialog to open at all.
    expect(screen.queryByRole("dialog", { name: "schema-dialog" })).not.toBeInTheDocument();
  });

  it("opens the sharing panel scoped to this table, with can_edit as can_manage", async () => {
    serve();
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");

    await user.click(screen.getByRole("button", { name: /share/i }));

    const panel = screen.getByTestId("sharing-panel");
    expect(panel).toHaveAttribute("data-resource", "table:t1");
    expect(panel).toHaveAttribute("data-can-manage", "true");
  });

  it("switches to the list view and writes the tab to the URL", async () => {
    serve();
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");

    await user.click(screen.getByRole("tab", { name: "List" }));

    expect(await screen.findByTestId("list-view")).toBeInTheDocument();
    expect(new URL(window.location.href).searchParams.get("view")).toBe("list");
  });

  it("asks for a grouped view before drawing the kanban board", async () => {
    serve({ viewsFixture: views({ items: [] }) });
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");

    await user.click(screen.getByRole("tab", { name: "Kanban" }));

    expect(
      await screen.findByText(/Save a kanban view with a grouping column/),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("kanban-view")).not.toBeInTheDocument();
  });

  it("draws the kanban board once a grouped view is active, passing its grouping column through", async () => {
    serve();
    arriveAt("view=kanban&viewId=v-kanban");
    renderPage();

    const kanban = await screen.findByTestId("kanban-view");
    expect(kanban).toHaveAttribute("data-group-by", "c2");
  });

  it("resets to the first page when switching to a different saved view, even after advancing past it", async () => {
    // The regression this guards: `page` used to carry over unchanged across a
    // view switch, so a page advanced under one view became the offset for the
    // next view's own (possibly much shorter) result - rendering the
    // empty-record state even though matching records exist on page zero.
    vi.mocked(apiClient.get).mockImplementation((path: string) => {
      if (path === "/tables/t1") return Promise.resolve(table());
      if (path === "/tables/t1/views") return Promise.resolve(views());
      return Promise.resolve({ items: [], total: 0 });
    });
    const queryBodies: { skip?: number }[] = [];
    vi.mocked(apiClient.post).mockImplementation((path: string, body?: unknown) => {
      if (path === "/tables/t1/records/query") {
        queryBodies.push(body as { skip?: number });
        return Promise.resolve({ items: [RECORD], has_more: true });
      }
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(queryBodies.some((body) => body.skip === PAGE_SIZE)).toBe(true));

    await user.click(screen.getByRole("combobox", { name: /select a table view/i }));
    await user.click(screen.getByRole("option", { name: "By customer" }));

    await waitFor(() => expect(queryBodies[queryBodies.length - 1]?.skip).toBe(0));
  });

  it("opens the record sheet from a grid row and advances it with each update", async () => {
    serve();
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");

    await user.click(screen.getByRole("button", { name: "open-record-from-grid" }));
    const sheet = screen.getByRole("dialog", { name: "record-sheet" });
    expect(sheet).toHaveAttribute("data-record-id", "r1");
    expect(sheet).toHaveAttribute("data-revision", "1");

    act(() => sheetProps?.onRecordUpdated({ ...RECORD, revision: 2 }));

    expect(screen.getByRole("dialog", { name: "record-sheet" })).toHaveAttribute(
      "data-revision",
      "2",
    );
  });

  it("keeps a closed record sheet closed when a commit lands after the close", async () => {
    // A field committed on the blur the closing click caused answers one round
    // trip later; storing that answer as "the open record" reopened the sheet.
    serve();
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");
    await user.click(screen.getByRole("button", { name: "open-record-from-grid" }));

    act(() => sheetProps?.onOpenChange(false));
    act(() => sheetProps?.onRecordUpdated({ ...RECORD, revision: 2 }));

    expect(screen.queryByRole("dialog", { name: "record-sheet" })).not.toBeInTheDocument();
  });

  it("does not swap the open record for a different one's late update", async () => {
    serve();
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");
    await user.click(screen.getByRole("button", { name: "open-record-from-grid" }));

    act(() => sheetProps?.onRecordUpdated({ ...RECORD, id: "r2", revision: 7 }));

    const sheet = screen.getByRole("dialog", { name: "record-sheet" });
    expect(sheet).toHaveAttribute("data-record-id", "r1");
    expect(sheet).toHaveAttribute("data-revision", "1");
  });
});
