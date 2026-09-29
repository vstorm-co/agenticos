import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TableDetailPage from "./page";
import { apiClient, ApiError } from "@/lib/api-client";
import { toast } from "sonner";
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
    canEdit,
    onAddRecord,
    columnActions,
    onAddColumn,
    records,
    onEndReached,
  }: {
    columns: { id: string; label: string }[];
    sort: { by: string; direction: string };
    onSort: (sort: { by: string; direction: string }) => void;
    onOpenRecord: (r: RecordRead) => void;
    canEdit: boolean;
    onAddRecord?: () => void;
    columnActions?: Record<"onSort" | "onRename" | "onHide" | "onArchive", (arg: unknown) => void>;
    onAddColumn?: () => void;
    records: RecordRead[];
    onEndReached: () => void;
  }) => (
    <div
      data-testid="grid-view"
      data-record-count={records.length}
      data-column-ids={columns.map((c) => c.id).join(",")}
      data-sort={`${sort.by}:${sort.direction}`}
      data-can-edit={String(canEdit)}
    >
      <button onClick={() => onOpenRecord({ ...RECORD })}>open-record-from-grid</button>
      <button onClick={() => onSort({ by: "name", direction: "desc" })}>resort-by-name</button>
      {onAddRecord && <button onClick={onAddRecord}>add-from-empty-grid</button>}
      {onAddColumn && <button onClick={onAddColumn}>add-column</button>}
      <button onClick={onEndReached}>scroll-to-end</button>
      {columnActions &&
        columns.map((column) => (
          <span key={column.id}>
            <button onClick={() => columnActions.onRename(column)}>rename-{column.id}</button>
            <button onClick={() => columnActions.onHide(column)}>hide-{column.id}</button>
            <button onClick={() => columnActions.onArchive(column)}>archive-{column.id}</button>
          </span>
        ))}
    </div>
  ),
}));
const exportRecords = vi.fn();
vi.mock("@/lib/tables-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/tables-api")>("@/lib/tables-api");
  return { ...actual, exportRecords: (...args: unknown[]) => exportRecords(...args) };
});
vi.mock("@/components/tables/import-csv-dialog", () => ({
  ImportCsvDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog" aria-label="import-dialog" /> : null,
}));
vi.mock("@/components/tables/new-record-dialog", () => ({
  NewRecordDialog: ({
    open,
    onOpenChange,
  }: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
  }) =>
    open ? (
      <div role="dialog" aria-label="new-record-dialog">
        <button onClick={() => onOpenChange(false)}>close-new-record</button>
      </div>
    ) : null,
}));
vi.mock("@/components/tables/table-list-view", () => ({
  TableListView: () => <div data-testid="list-view" />,
}));
vi.mock("@/components/tables/table-kanban-view", () => ({
  TableKanbanView: ({
    groupByColumnId,
    baseFilters,
    search,
  }: {
    groupByColumnId: string;
    baseFilters: unknown[];
    search: string | null;
  }) => (
    <div
      data-testid="kanban-view"
      data-group-by={groupByColumnId}
      data-filters={JSON.stringify(baseFilters)}
      data-search={String(search)}
    />
  ),
}));
const COMPLETE = { column_id: "c1", op: "contains", value: "ad" };
const DRAFT = { column_id: "c1", op: "contains", value: null };
vi.mock("@/components/tables/record-filters-popover", () => ({
  RecordFiltersPopover: ({
    columns,
    onChange,
  }: {
    columns: { id: string }[];
    onChange: (filters: unknown[]) => void;
  }) => (
    <div data-testid="filters" data-column-ids={columns.map((c) => c.id).join(",")}>
      <button onClick={() => onChange([COMPLETE, DRAFT])}>set-filters</button>
    </div>
  ),
}));
vi.mock("@/components/tables/schema-editor-dialog", () => ({
  SchemaEditorDialog: ({
    open,
    error,
    onSave,
    onOpenChange,
  }: {
    open: boolean;
    error: unknown;
    onSave: (columns: unknown[]) => void;
    onOpenChange: (open: boolean) => void;
  }) =>
    open ? (
      <div role="dialog" aria-label="schema-dialog" data-error={error ? "shown" : "none"}>
        <button onClick={() => onSave([])}>save-schema</button>
        <button onClick={() => onOpenChange(false)}>close-schema</button>
      </div>
    ) : null,
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
vi.mock("@/components/tables/triggers/table-triggers-panel", () => ({
  TableTriggersPanel: ({
    tableId,
    columns,
    canEdit,
  }: {
    tableId: string;
    columns: unknown[];
    canEdit: boolean;
  }) => (
    <div
      data-testid="triggers-panel"
      data-table={tableId}
      data-columns={columns.length}
      data-can-edit={String(canEdit)}
    />
  ),
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
  search: null,
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
        can_delete: true,
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
        can_delete: true,
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
      return Promise.resolve({ items: [RECORD], skip: 0, limit: 100, has_more: false });
    if (path === "/tables/t1/records/count") return Promise.resolve({ count: 1, capped: false });
    return Promise.resolve({});
  });
}

const PARAMS = Promise.resolve({ id: "t1" });

function renderPage() {
  return render(<TableDetailPage params={PARAMS} />, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
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
    vi.mocked(apiClient.post).mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
  });

  it("shows the table's name, description and visibility", async () => {
    serve();
    renderPage();

    expect(await screen.findByRole("heading", { name: "Orders" })).toBeInTheDocument();
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

  it("lets an editor add a record from the header or the empty grid", async () => {
    serve();
    const user = userEvent.setup();
    renderPage();
    const grid = await screen.findByTestId("grid-view");
    expect(grid).toHaveAttribute("data-can-edit", "true");

    await user.click(screen.getByRole("button", { name: /add record/i }));
    expect(screen.getByRole("dialog", { name: "new-record-dialog" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "close-new-record" }));
    expect(screen.queryByRole("dialog", { name: "new-record-dialog" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "add-from-empty-grid" }));
    expect(screen.getByRole("dialog", { name: "new-record-dialog" })).toBeInTheDocument();
  });

  it("offers a viewer without can_edit no way to add a record", async () => {
    serve({ tableFixture: table({ can_edit: false }) });
    renderPage();
    const grid = await screen.findByTestId("grid-view");

    expect(grid).toHaveAttribute("data-can-edit", "false");
    expect(screen.queryByRole("button", { name: /add record/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "add-from-empty-grid" })).not.toBeInTheDocument();
  });

  describe("narrowing the records", () => {
    const lastQuery = () =>
      vi
        .mocked(apiClient.post)
        .mock.calls.filter(([path]) => path === "/tables/t1/records/query")
        .at(-1)?.[1] as { filters: unknown[]; search: string | null };

    it("sends the search once typing settles, and only the complete conditions", async () => {
      serve();
      const user = userEvent.setup();
      renderPage();
      await screen.findByTestId("grid-view");
      expect(screen.getByTestId("filters")).toHaveAttribute("data-column-ids", "c1,c2");

      await user.type(screen.getByPlaceholderText("Search records"), "  ada ");
      await waitFor(() => expect(lastQuery().search).toBe("ada"));

      await user.click(screen.getByRole("button", { name: "set-filters" }));
      await waitFor(() => expect(lastQuery().filters).toEqual([COMPLETE]));
    });

    it("narrows every kanban lane the same way", async () => {
      serve();
      arriveAt("view=kanban&viewId=v-kanban");
      const user = userEvent.setup();
      renderPage();
      const board = await screen.findByTestId("kanban-view");

      await user.click(screen.getByRole("button", { name: "set-filters" }));

      expect(board).toHaveAttribute("data-filters", JSON.stringify([COMPLETE]));
      expect(board).toHaveAttribute("data-search", "null");
    });

    it("offers to save a changed view to whoever manages it, and saves into it", async () => {
      serve();
      arriveAt("viewId=v-table");
      vi.mocked(apiClient.patch).mockResolvedValueOnce({});
      const user = userEvent.setup();
      renderPage();
      await screen.findByTestId("grid-view");
      expect(screen.queryByRole("button", { name: "Save view" })).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "set-filters" }));
      await user.click(screen.getByRole("button", { name: "Save view" }));

      await waitFor(() => expect(toast.success).toHaveBeenCalledWith("View saved."));
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/views/v-table", {
        config: {
          ...emptyConfig,
          sort: { by: "c1", direction: "desc" },
          filters: [COMPLETE],
          search: null,
        },
      });
    });

    it("says so when saving the view is refused", async () => {
      serve();
      arriveAt("viewId=v-table");
      vi.mocked(apiClient.patch).mockRejectedValueOnce(new ApiError(404, "View not found"));
      const user = userEvent.setup();
      renderPage();
      await screen.findByTestId("grid-view");

      await user.click(screen.getByRole("button", { name: "set-filters" }));
      await user.click(screen.getByRole("button", { name: "Save view" }));

      await waitFor(() => expect(toast.error).toHaveBeenCalledWith("View not found"));
    });

    it("offers no save of a view the caller cannot manage", async () => {
      const readOnly = views();
      readOnly.items = readOnly.items.map((view) => ({ ...view, can_manage: false }));
      serve({ viewsFixture: readOnly });
      arriveAt("viewId=v-table");
      const user = userEvent.setup();
      renderPage();
      await screen.findByTestId("grid-view");

      await user.click(screen.getByRole("button", { name: "set-filters" }));

      expect(screen.queryByRole("button", { name: "Save view" })).not.toBeInTheDocument();
    });

    it("keeps what the screen is narrowed by in a new view", async () => {
      serve();
      vi.mocked(apiClient.post).mockImplementation((path: string) => {
        if (path === "/tables/t1/records/query")
          return Promise.resolve({ items: [RECORD], has_more: false });
        return Promise.resolve({ ...views().items[1], id: "v-new" });
      });
      const user = userEvent.setup();
      renderPage();
      await screen.findByTestId("grid-view");

      await user.click(screen.getByRole("button", { name: "set-filters" }));
      await user.click(screen.getByRole("button", { name: "New view" }));
      await user.type(screen.getByRole("textbox", { name: "View name" }), "Ada's");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() =>
        expect(apiClient.post).toHaveBeenCalledWith("/tables/t1/views", {
          name: "Ada's",
          kind: "table",
          visibility: "private",
          config: { ...emptyConfig, filters: [COMPLETE] },
        }),
      );
    });
  });

  describe("records in and out as CSV", () => {
    it("exports what the screen shows, and says why when it cannot", async () => {
      serve();
      exportRecords
        .mockResolvedValueOnce(undefined)
        .mockRejectedValueOnce(new ApiError(413, "Too many"));
      const user = userEvent.setup();
      renderPage();
      await screen.findByTestId("grid-view");

      await user.click(screen.getByRole("button", { name: "Export" }));
      await waitFor(() =>
        expect(exportRecords).toHaveBeenCalledWith("t1", {
          filters: [],
          search: null,
          sort: { by: "created_at", direction: "asc" },
          columns: ["c1", "c2"],
        }),
      );
      await waitFor(() => expect(screen.getByRole("button", { name: "Export" })).toBeEnabled());
      await user.click(screen.getByRole("button", { name: "Export" }));
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Too many"));
    });

    it("offers the import to an editor only", async () => {
      serve();
      const user = userEvent.setup();
      renderPage();
      await screen.findByTestId("grid-view");

      await user.click(screen.getByRole("button", { name: "Import" }));
      expect(screen.getByRole("dialog", { name: "import-dialog" })).toBeInTheDocument();
    });

    it("hides the import from a reader, who can still export", async () => {
      serve({ tableFixture: table({ can_edit: false }) });
      renderPage();
      await screen.findByTestId("grid-view");

      expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
    });
  });

  describe("a large table", () => {
    it("says how many records match", async () => {
      serve();
      renderPage();

      expect(await screen.findByText("1 record")).toBeInTheDocument();
      const counted = vi
        .mocked(apiClient.post)
        .mock.calls.find(([path]) => path === "/tables/t1/records/count");
      expect(counted?.[1]).toEqual({ filters: [], search: null });
    });

    it("says when more match than the service counts", async () => {
      serve();
      const fallback = vi.mocked(apiClient.post).getMockImplementation()!;
      vi.mocked(apiClient.post).mockImplementation((path: string, body?: unknown) =>
        path === "/tables/t1/records/count"
          ? Promise.resolve({ count: 100000, capped: true })
          : fallback(path, body),
      );
      renderPage();

      expect(await screen.findByText("100,000+ records")).toBeInTheDocument();
    });

    it("loads the next hundred records as the grid nears its end, then stops at the last", async () => {
      serve();
      const bodies: { skip: number }[] = [];
      let releaseSecond!: () => void;
      vi.mocked(apiClient.post).mockImplementation((path: string, body?: unknown) => {
        if (path === "/tables/t1/records/count")
          return Promise.resolve({ count: 2, capped: false });
        const { skip } = body as { skip: number };
        bodies.push({ skip });
        if (skip === 0)
          return Promise.resolve({ items: [RECORD], skip, limit: 100, has_more: true });
        return new Promise((resolve) => {
          releaseSecond = () =>
            resolve({ items: [{ ...RECORD, id: "r2" }], skip, limit: 100, has_more: false });
        });
      });
      const user = userEvent.setup();
      renderPage();
      const grid = await screen.findByTestId("grid-view");
      await waitFor(() => expect(grid).toHaveAttribute("data-record-count", "1"));

      await user.click(screen.getByRole("button", { name: "scroll-to-end" }));
      expect(await screen.findByText("Loading more records…")).toBeInTheDocument();
      // A second nudge while a page is loading asks for nothing more.
      await user.click(screen.getByRole("button", { name: "scroll-to-end" }));
      act(() => releaseSecond());

      await waitFor(() => expect(grid).toHaveAttribute("data-record-count", "2"));
      await user.click(screen.getByRole("button", { name: "scroll-to-end" }));
      expect(bodies.map((body) => body.skip)).toEqual([0, 100]);
    });

    it("says where scrolling ends when the service can skip no further", async () => {
      serve();
      vi.mocked(apiClient.post).mockImplementation((path: string, body?: unknown) => {
        if (path === "/tables/t1/records/count")
          return Promise.resolve({ count: 100000, capped: true });
        const { skip } = body as { skip: number };
        return Promise.resolve({ items: [RECORD], skip: 10_000, limit: 100, has_more: skip >= 0 });
      });
      renderPage();

      expect(
        await screen.findByText(
          "The grid scrolls through the first 10,000 records. Filter or search to reach the rest.",
        ),
      ).toBeInTheDocument();
    });
  });

  describe("managing columns from the grid", () => {
    const savedWith = () =>
      vi.mocked(apiClient.put).mock.calls.at(-1)?.[1] as {
        expected_version: number;
        columns: { id?: string; label: string; archived?: boolean }[];
      };

    it("offers a reader no column actions", async () => {
      serve({ tableFixture: table({ can_edit: false }) });
      renderPage();
      await screen.findByTestId("grid-view");

      expect(screen.queryByRole("button", { name: "rename-c1" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "add-column" })).not.toBeInTheDocument();
    });

    it("renames a column as one schema version of every column", async () => {
      serve();
      vi.mocked(apiClient.put).mockResolvedValueOnce(table());
      const user = userEvent.setup();
      renderPage();
      await screen.findByTestId("grid-view");

      await user.click(screen.getByRole("button", { name: "rename-c1" }));
      const name = screen.getByLabelText("Name");
      await user.clear(name);
      await user.type(name, "Client");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => expect(apiClient.put).toHaveBeenCalled());
      expect(savedWith().expected_version).toBe(1);
      expect(savedWith().columns.map((column) => [column.id, column.label])).toEqual([
        ["c1", "Client"],
        ["c2", "Status"],
        ["c3", "Retired"],
      ]);
      await waitFor(() => expect(screen.queryByLabelText("Name")).not.toBeInTheDocument());
    });

    it("archives a column after asking, and says why when it is refused", async () => {
      serve();
      vi.mocked(apiClient.put).mockRejectedValueOnce(
        new ApiError(409, "The view Open orders filters on this column"),
      );
      const user = userEvent.setup();
      renderPage();
      await screen.findByTestId("grid-view");

      await user.click(screen.getByRole("button", { name: "archive-c2" }));
      expect(screen.getByText("Archive Status?")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Archive column" }));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith("The view Open orders filters on this column"),
      );
      expect(savedWith().columns.find((column) => column.id === "c2")?.archived).toBe(true);

      vi.mocked(apiClient.put).mockResolvedValueOnce(table());
      await user.click(screen.getByRole("button", { name: "Archive column" }));
      await waitFor(() => expect(screen.queryByText("Archive Status?")).not.toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: "archive-c1" }));
      await user.click(screen.getByRole("button", { name: "Cancel" }));
      expect(screen.queryByText("Archive Customer?")).not.toBeInTheDocument();
    });

    it("hides a column on this screen, shows it back, and adds one that shows", async () => {
      serve();
      const withRegion = table();
      withRegion.columns = [
        ...withRegion.columns,
        { ...withRegion.columns[0]!, id: "c4", label: "Region" },
      ];
      vi.mocked(apiClient.put).mockResolvedValueOnce(withRegion);
      const user = userEvent.setup();
      renderPage();
      const grid = await screen.findByTestId("grid-view");

      await user.click(screen.getByRole("button", { name: "hide-c2" }));
      expect(grid).toHaveAttribute("data-column-ids", "c1");
      await user.click(screen.getByRole("button", { name: "1 hidden" }));
      await user.click(screen.getByRole("button", { name: "Status" }));
      expect(grid).toHaveAttribute("data-column-ids", "c1,c2");

      await user.click(screen.getByRole("button", { name: "hide-c2" }));
      await user.click(screen.getByRole("button", { name: "hide-c1" }));
      expect(grid).toHaveAttribute("data-column-ids", "");
      await user.click(screen.getByRole("button", { name: "add-column" }));
      await user.type(screen.getByLabelText("Name"), "Region");
      // The table read again after the save has the new column.
      serve({ tableFixture: withRegion });
      await user.click(screen.getByRole("button", { name: "Add column" }));

      await waitFor(() => expect(grid).toHaveAttribute("data-column-ids", "c4"));
      expect(savedWith().columns.at(-1)).toEqual({
        label: "Region",
        type: "text",
        nullable: true,
        options: [],
      });
      await user.click(screen.getByRole("button", { name: "2 hidden" }));
      await user.click(screen.getByRole("button", { name: "Show all columns" }));
      expect(grid).toHaveAttribute("data-column-ids", "c1,c2,c4");
    });

    it("adds a column to a screen that shows every one without narrowing it", async () => {
      serve();
      vi.mocked(apiClient.put).mockResolvedValueOnce(table());
      const user = userEvent.setup();
      renderPage();
      const grid = await screen.findByTestId("grid-view");

      await user.click(screen.getByRole("button", { name: "add-column" }));
      await user.type(screen.getByLabelText("Name"), "Region");
      await user.click(screen.getByRole("button", { name: "Add column" }));

      await waitFor(() => expect(apiClient.put).toHaveBeenCalled());
      expect(grid).toHaveAttribute("data-column-ids", "c1,c2");
    });
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

  it("opens the table's triggers in a sheet, with every column and can_edit, and closes it", async () => {
    serve();
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");

    await user.click(screen.getByRole("button", { name: /triggers/i }));

    const panel = screen.getByTestId("triggers-panel");
    expect(panel).toHaveAttribute("data-table", "t1");
    expect(panel).toHaveAttribute("data-can-edit", "true");
    expect(screen.getByRole("heading", { name: "When a record is added" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /close/i }));
    expect(screen.queryByTestId("triggers-panel")).not.toBeInTheDocument();
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

  it("resets the list to its first page when switching to a different saved view, even after advancing past it", async () => {
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
    arriveAt("view=list");
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("list-view");

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(queryBodies.some((body) => body.skip === PAGE_SIZE)).toBe(true));

    await user.click(screen.getByRole("combobox", { name: /select a list view/i }));
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

  it("does not step the open record back to an older revision answered late", async () => {
    // A reload read before a write landed can answer after it; taking its
    // older record put the value just written back to the one before.
    serve();
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");
    await user.click(screen.getByRole("button", { name: "open-record-from-grid" }));

    act(() => sheetProps?.onRecordUpdated({ ...RECORD, revision: 3 }));
    act(() => sheetProps?.onRecordUpdated({ ...RECORD, revision: 2 }));

    expect(screen.getByRole("dialog", { name: "record-sheet" })).toHaveAttribute(
      "data-revision",
      "3",
    );
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

  it("keeps a view selected when deleting it is refused, and deselects it once a delete lands", async () => {
    serve();
    arriveAt("viewId=v-table");
    vi.mocked(apiClient.delete).mockRejectedValueOnce(new ApiError(404, "View not found"));
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");

    async function deleteActive() {
      await user.click(screen.getByRole("button", { name: /^delete$/i }));
      const confirm = screen.getByRole("dialog");
      await user.click(within(confirm).getByRole("button", { name: /^delete$/i }));
    }

    await deleteActive();
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("View not found"));
    expect(new URL(window.location.href).searchParams.get("viewId")).toBe("v-table");
    expect(screen.getByRole("combobox", { name: /select a table view/i })).toHaveTextContent(
      "By customer",
    );

    vi.mocked(apiClient.delete).mockResolvedValueOnce(undefined);
    await deleteActive();
    await waitFor(() =>
      expect(new URL(window.location.href).searchParams.get("viewId")).toBeNull(),
    );
  });

  it("holds the list's pager while the next page is still loading", async () => {
    // The previous page stands in as placeholder data while the next one
    // loads; its `has_more` kept "Next" enabled, so a double click skipped a
    // page and could land past the end.
    serve();
    let releaseSecondPage!: () => void;
    vi.mocked(apiClient.post).mockImplementation((path: string, body?: unknown) => {
      if (path !== "/tables/t1/records/query") return Promise.resolve({});
      if ((body as { skip: number }).skip === 0)
        return Promise.resolve({ items: [RECORD], has_more: true });
      return new Promise((resolve) => {
        releaseSecondPage = () => resolve({ items: [RECORD], has_more: true });
      });
    });
    arriveAt("view=list");
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("list-view");
    await waitFor(() => expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled());

    await user.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled());
    act(() => releaseSecondPage());
    await waitFor(() => expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled());
  });

  it("refetches the table when the sharing dialog closes, so its visibility badge is current", async () => {
    serve();
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");
    await user.click(screen.getByRole("button", { name: /share/i }));
    vi.mocked(apiClient.get).mockClear();

    await user.keyboard("{Escape}");

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/tables/t1"));
  });

  it("opens the schema editor without the last save's refusal", async () => {
    serve();
    vi.mocked(apiClient.put).mockRejectedValueOnce(new ApiError(409, "Schema changed"));
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("grid-view");
    await user.click(screen.getByRole("button", { name: /columns/i }));
    await user.click(screen.getByRole("button", { name: "save-schema" }));
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "schema-dialog" })).toHaveAttribute(
        "data-error",
        "shown",
      ),
    );

    await user.click(screen.getByRole("button", { name: "close-schema" }));
    await user.click(screen.getByRole("button", { name: /columns/i }));

    expect(screen.getByRole("dialog", { name: "schema-dialog" })).toHaveAttribute(
      "data-error",
      "none",
    );
  });
});
