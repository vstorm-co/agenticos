import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TableKanbanView } from "./table-kanban-view";
import { apiClient, ApiError } from "@/lib/api-client";
import { useTableViewStore } from "@/stores";
import type { ColumnDef, RecordRead } from "@/types/tables";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const GROUP_BY: ColumnDef = {
  id: "status",
  label: "Status",
  type: "single_select",
  nullable: true,
  default: null,
  options: [
    { id: "o1", label: "Open", archived: false },
    { id: "o2", label: "Closed", archived: false },
    { id: "o3", label: "Retired", archived: true },
  ],
  archived: false,
};
const TITLE: ColumnDef = {
  id: "name",
  label: "Name",
  type: "text",
  nullable: true,
  default: null,
  options: [],
  archived: false,
};
const PAID: ColumnDef = {
  id: "paid",
  label: "Paid",
  type: "boolean",
  nullable: true,
  default: null,
  options: [],
  archived: false,
};
const COLUMNS = [TITLE, GROUP_BY];

function record(id: string, statusValue: string | null, revision = 1): RecordRead {
  return {
    id,
    table_id: "t1",
    external_id: null,
    schema_version: 1,
    values: { name: `Record ${id}`, status: statusValue },
    revision,
    created_at: "2026-09-23T00:00:00Z",
  };
}

function laneOf(filters: { column_id: string; op: string; value?: unknown }[]): string {
  const clause = filters.find((f) => f.column_id === "status");
  if (!clause) return "unfiltered";
  if (clause.op === "is_null") return "none";
  if (clause.op === "in") return "archived";
  return String(clause.value);
}

function mockLanes(byLane: Record<string, RecordRead[]>) {
  vi.mocked(apiClient.post).mockImplementation(async (url: string, body?: unknown) => {
    if (url.endsWith("/records/query")) {
      const { filters } = body as { filters: { column_id: string; op: string; value?: unknown }[] };
      const lane = laneOf(filters);
      const items = byLane[lane] ?? [];
      return { items, skip: 0, limit: 25, has_more: false };
    }
    return { id: "unused" };
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  useTableViewStore.getState().reset();
});

describe("TableKanbanView", () => {
  it("shows a fallback message when the grouping column is not a single_select", () => {
    render(
      <TableKanbanView
        tableId="t1"
        columns={[TITLE]}
        groupByColumnId="missing"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    expect(screen.getByText(/needs a single-select grouping column/i)).toBeInTheDocument();
  });

  it("renders one lane per live option, plus no-value and archived", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );

    expect(await screen.findByText("Record r1")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText("Closed")).toBeInTheDocument();
    expect(screen.getByText("No value")).toBeInTheDocument();
    expect(screen.getByText("Archived")).toBeInTheDocument();
  });

  it("opens a record when its card title is clicked", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    const onOpenRecord = vi.fn();
    const user = userEvent.setup();
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={onOpenRecord}
        canEdit
      />,
      { wrapper },
    );

    const card = await screen.findByText("Record r1");
    await user.click(card);

    expect(onOpenRecord).toHaveBeenCalledWith(record("r1", "o1"));
  });

  it("moves a card via the keyboard-reachable Move to menu", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "r1", revision: 2 });
    const user = userEvent.setup();
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    await screen.findByText("Record r1");

    await user.click(screen.getByRole("button", { name: /move to/i }));
    await user.click(screen.getByRole("menuitem", { name: "Closed" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
        expected_revision: 1,
        values: { status: "o2" },
      }),
    );
  });

  it("gives a read-only caller no Move to menu and no draggable card - absent, not merely refused", async () => {
    // The backend already refuses the write; this is the repository's own
    // rule that an unauthorized control is not rendered at all, not rendered
    // and then 403 (.claude/rules/frontend.md's Permissions section).
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit={false}
      />,
      { wrapper },
    );
    const card = await screen.findByText("Record r1");

    expect(screen.queryByRole("button", { name: /move to/i })).not.toBeInTheDocument();
    const cardRoot = card.closest("div[draggable]");
    expect(cardRoot).toHaveAttribute("draggable", "false");
  });

  it("the Move to menu excludes the lane the card is already in", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    const user = userEvent.setup();
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    await screen.findByText("Record r1");

    await user.click(screen.getByRole("button", { name: /move to/i }));

    expect(screen.queryByRole("menuitem", { name: "Open" })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Closed" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "No value" })).toBeInTheDocument();
  });

  it("shows a conflict banner on a stale move, offering reload-and-reapply and discard", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    const user = userEvent.setup();
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    await screen.findByText("Record r1");

    await user.click(screen.getByRole("button", { name: /move to/i }));
    await user.click(screen.getByRole("menuitem", { name: "Closed" }));

    expect(await screen.findByText(/someone else changed this record/i)).toBeInTheDocument();

    // Discard clears the banner without another write.
    vi.mocked(apiClient.patch).mockClear();
    await user.click(screen.getByRole("button", { name: /discard/i }));
    expect(screen.queryByText(/someone else changed this record/i)).not.toBeInTheDocument();
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("does not show a conflict banner for a conflict on this record about a different field", async () => {
    // The conflict store holds one entry per record, shared with the record
    // detail sheet - a stale edit to some other column of this same record
    // (fieldId "name", say) sets a conflict here too. That conflict is not
    // about the grouping column, so the kanban card must stay quiet about it;
    // showing it (or worse, offering "reload and reapply") would let the
    // board attempt to move the record into the "no value" lane over an edit
    // it never made.
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    await screen.findByText("Record r1");

    useTableViewStore.getState().setConflict({
      recordId: "r1",
      pendingValues: { name: "Renamed" },
      fieldId: "name",
    });

    expect(screen.queryByText(/someone else changed this record/i)).not.toBeInTheDocument();
  });

  it("discard refetches every lane, rather than only clearing the local banner", async () => {
    // No optimistic move was ever applied client-side, so a discard's own job
    // is bringing the lanes back in line with the row a conflict just proved
    // had changed server-side - not merely hiding the banner.
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    const user = userEvent.setup();
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    await screen.findByText("Record r1");
    await user.click(screen.getByRole("button", { name: /move to/i }));
    await user.click(screen.getByRole("menuitem", { name: "Closed" }));
    await screen.findByText(/someone else changed this record/i);

    vi.mocked(apiClient.post).mockClear();
    await user.click(screen.getByRole("button", { name: /discard/i }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/tables/t1/records/query", expect.anything()),
    );
  });

  it("a failed reload does not clear the pending move - there would be no way back to it", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    vi.mocked(apiClient.get).mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    await screen.findByText("Record r1");
    await user.click(screen.getByRole("button", { name: /move to/i }));
    await user.click(screen.getByRole("menuitem", { name: "Closed" }));
    await screen.findByText(/someone else changed this record/i);

    await user.click(screen.getByRole("button", { name: /reload and reapply/i }));

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/tables/t1/records/r1"));
    expect(screen.getByText(/someone else changed this record/i)).toBeInTheDocument();
  });

  it("reload-and-reapply refetches the record and retries against its fresh revision", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    vi.mocked(apiClient.get).mockResolvedValue(record("r1", "o1", 5));
    const user = userEvent.setup();
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    await screen.findByText("Record r1");
    await user.click(screen.getByRole("button", { name: /move to/i }));
    await user.click(screen.getByRole("menuitem", { name: "Closed" }));
    await screen.findByText(/someone else changed this record/i);

    vi.mocked(apiClient.patch).mockResolvedValueOnce({ id: "r1", revision: 6 });
    await user.click(screen.getByRole("button", { name: /reload and reapply/i }));

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/tables/t1/records/r1"));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
        expected_revision: 5,
        values: { status: "o2" },
      }),
    );
  });

  it("keeps the conflict banner when the retry move itself fails, not only when the refetch does", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    vi.mocked(apiClient.get).mockResolvedValue(record("r1", "o1", 5));
    const user = userEvent.setup();
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    await screen.findByText("Record r1");
    await user.click(screen.getByRole("button", { name: /move to/i }));
    await user.click(screen.getByRole("menuitem", { name: "Closed" }));
    await screen.findByText(/someone else changed this record/i);

    vi.mocked(apiClient.patch).mockRejectedValueOnce(new Error("network down"));
    await user.click(screen.getByRole("button", { name: /reload and reapply/i }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenLastCalledWith("/tables/t1/records/r1", {
        expected_revision: 5,
        values: { status: "o2" },
      }),
    );
    expect(screen.getByText(/someone else changed this record/i)).toBeInTheDocument();
  });

  it("formats a boolean title column through the cells translations", async () => {
    mockLanes({
      o1: [{ ...record("r1", "o1"), values: { paid: true, status: "o1" } }],
      o2: [],
      none: [],
      archived: [],
    });
    render(
      <TableKanbanView
        tableId="t1"
        columns={[PAID, GROUP_BY]}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );

    expect(await screen.findByRole("button", { name: "True" })).toBeInTheDocument();
  });

  it("formats a false boolean title column as 'False', not empty", async () => {
    mockLanes({
      o1: [{ ...record("r1", "o1"), values: { paid: false, status: "o1" } }],
      o2: [],
      none: [],
      archived: [],
    });
    render(
      <TableKanbanView
        tableId="t1"
        columns={[PAID, GROUP_BY]}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );

    expect(await screen.findByRole("button", { name: "False" })).toBeInTheDocument();
  });

  it("falls back to the record id when the title column has no stored value", async () => {
    mockLanes({
      o1: [{ ...record("r1", "o1"), values: { status: "o1" } }],
      o2: [],
      none: [],
      archived: [],
    });
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );

    expect(await screen.findByRole("button", { name: "r1" })).toBeInTheDocument();
  });

  it("dragging a card into another lane writes the same move a Move-to click would", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "r1", revision: 2 });
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    const card = await screen.findByText("Record r1");
    const cardRoot = card.closest("div[draggable]") as HTMLElement;
    const closedLabel = screen.getByText("Closed");
    const laneRoot = closedLabel.closest("div.flex.w-64") as HTMLElement;

    fireEvent.dragStart(cardRoot);
    fireEvent.dragOver(laneRoot);
    fireEvent.drop(laneRoot);

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
        expected_revision: 1,
        values: { status: "o2" },
      }),
    );
  });

  it("a non-conflict move failure sets no conflict banner", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    vi.mocked(apiClient.patch).mockRejectedValueOnce(new ApiError(422, "invalid"));
    const user = userEvent.setup();
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    await screen.findByText("Record r1");

    await user.click(screen.getByRole("button", { name: /move to/i }));
    await user.click(screen.getByRole("menuitem", { name: "Closed" }));

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    expect(screen.queryByText(/someone else changed this record/i)).not.toBeInTheDocument();
  });

  it("dropping on the archived lane is refused client-side, firing no write", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    const card = await screen.findByText("Record r1");
    const cardRoot = card.closest("div[draggable]") as HTMLElement;
    const archivedLabel = screen.getByText("Archived");
    const laneRoot = archivedLabel.closest("div.flex.w-64") as HTMLElement;

    fireEvent.dragStart(cardRoot);
    fireEvent.dragOver(laneRoot);
    fireEvent.drop(laneRoot);

    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("an archived card's disabled drag handlers are inert no-ops", async () => {
    mockLanes({ o1: [], o2: [], none: [], archived: [record("r1", "o3")] });
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );
    const card = await screen.findByText("Record r1");
    const cardRoot = card.closest("div[draggable]") as HTMLElement;

    // `draggable=false` only stops the browser from starting a drag - it does
    // not stop these handlers from being dispatched, so both must be true
    // no-ops rather than rely on the browser never calling them.
    expect(() => {
      fireEvent.dragStart(cardRoot);
      fireEvent.dragEnd(cardRoot);
    }).not.toThrow();
  });

  it("the archived lane's cards are not draggable, and dropping on it is refused before any write", async () => {
    mockLanes({ o1: [], o2: [], none: [], archived: [record("r1", "o3")] });
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );

    const card = await screen.findByText("Record r1");
    const cardRoot = card.closest("div[draggable]");
    expect(cardRoot).toHaveAttribute("draggable", "false");
  });

  it("skips fetching the archived lane entirely when no option is archived", async () => {
    const noArchivedOptions: ColumnDef = { ...GROUP_BY, options: GROUP_BY.options.slice(0, 2) };
    mockLanes({ o1: [], o2: [], none: [] });
    render(
      <TableKanbanView
        tableId="t1"
        columns={[TITLE, noArchivedOptions]}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );

    await waitFor(() => expect(screen.getAllByText(/no records/i).length).toBeGreaterThan(0));
    const archivedCalls = vi.mocked(apiClient.post).mock.calls.filter(([url, body]) => {
      if (!url.endsWith("/records/query")) return false;
      const { filters } = body as { filters: { op: string }[] };
      return filters.some((f) => f.op === "in");
    });
    expect(archivedCalls).toHaveLength(0);
  });

  it("sends the required boolean operand on the no-value lane's is_null filter", async () => {
    // The regression this guards: the backend rejects an `is_null` filter with
    // no `value` (422, `is_null takes true or false`), and a record-query error
    // renders as an empty lane - so records without a grouping value silently
    // vanished from the board instead of showing up in "No value".
    const filtersSeen: { column_id: string; op: string; value?: unknown }[][] = [];
    vi.mocked(apiClient.post).mockImplementation(async (url: string, body?: unknown) => {
      if (url.endsWith("/records/query")) {
        const { filters } = body as {
          filters: { column_id: string; op: string; value?: unknown }[];
        };
        filtersSeen.push(filters);
        return { items: [], skip: 0, limit: 25, has_more: false };
      }
      return { id: "unused" };
    });
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );

    await waitFor(() => expect(filtersSeen.length).toBeGreaterThan(0));
    const noValueClause = filtersSeen
      .flat()
      .find((clause) => clause.column_id === "status" && clause.op === "is_null");
    expect(noValueClause).toEqual({ column_id: "status", op: "is_null", value: true });
  });

  it("shows a load-more hint when a lane has more records than fit one page", async () => {
    mockLanes({ o1: [record("r1", "o1")], o2: [], none: [], archived: [] });
    vi.mocked(apiClient.post).mockImplementation(async (url: string, body?: unknown) => {
      if (!url.endsWith("/records/query")) return { id: "unused" };
      const { filters } = body as { filters: { column_id: string; op: string; value?: unknown }[] };
      const lane = laneOf(filters);
      if (lane === "o1") return { items: [record("r1", "o1")], skip: 0, limit: 25, has_more: true };
      return { items: [], skip: 0, limit: 25, has_more: false };
    });
    render(
      <TableKanbanView
        tableId="t1"
        columns={COLUMNS}
        groupByColumnId="status"
        baseFilters={[]}
        sort={{ by: "created_at", direction: "asc" }}
        onOpenRecord={vi.fn()}
        canEdit
      />,
      { wrapper },
    );

    expect(await screen.findByText(/more records available/i)).toBeInTheDocument();
  });
});
