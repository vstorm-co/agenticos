import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps, ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TableGridView } from "./table-grid-view";
import { apiClient, ApiError } from "@/lib/api-client";
import { useTableViewStore } from "@/stores";
import type { ColumnDef, RecordRead } from "@/types/tables";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { patch: vi.fn(), delete: vi.fn() } };
});
const deleteLater = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-deferred-delete", () => ({ useDeferredDelete: () => deleteLater }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const columns: ColumnDef[] = [
  {
    id: "c1",
    label: "Name",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: false,
  },
  {
    id: "c2",
    label: "Tags",
    type: "multi_select",
    nullable: true,
    default: null,
    options: [{ id: "o1", label: "Rush", archived: false }],
    archived: false,
  },
];

const records: RecordRead[] = [
  {
    id: "r1",
    table_id: "t1",
    external_id: null,
    schema_version: 1,
    values: { c1: "Ada", c2: ["o1"] },
    revision: 1,
    created_at: "2026-09-23T00:00:00Z",
  },
];

const conflict409 = () =>
  new ApiError(409, "stale", {
    error: { code: "REVISION_CONFLICT", message: "stale", details: null },
  });

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

type GridProps = ComponentProps<typeof TableGridView>;

function renderEditable(overrides: Partial<GridProps> = {}) {
  const props: GridProps = {
    tableId: "t1",
    columns,
    records,
    isLoading: false,
    sort: { by: "created_at", direction: "asc" },
    onSort: vi.fn(),
    onOpenRecord: vi.fn(),
    canEdit: true,
    ...overrides,
  };
  render(<TableGridView {...props} />, { wrapper });
  return props;
}

beforeEach(() => {
  vi.clearAllMocks();
  useTableViewStore.getState().reset();
});

describe("TableGridView", () => {
  it("renders one column per live column and one row per record", () => {
    render(
      <TableGridView
        tableId="t1"
        canEdit={false}
        columns={columns}
        records={records}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("Rush")).toBeInTheDocument();
  });

  it("renders a boolean cell through the cells translations", () => {
    const boolColumn: ColumnDef = {
      id: "c3",
      label: "Paid",
      type: "boolean",
      nullable: true,
      default: null,
      options: [],
      archived: false,
    };
    render(
      <TableGridView
        tableId="t1"
        canEdit={false}
        columns={[boolColumn]}
        records={[{ ...records[0], values: { c3: true } } as RecordRead]}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByText("True")).toBeInTheDocument();
  });

  it("renders a false boolean cell", () => {
    const boolColumn: ColumnDef = {
      id: "c3",
      label: "Paid",
      type: "boolean",
      nullable: true,
      default: null,
      options: [],
      archived: false,
    };
    render(
      <TableGridView
        tableId="t1"
        canEdit={false}
        columns={[boolColumn]}
        records={[{ ...records[0], values: { c3: false } } as RecordRead]}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByText("False")).toBeInTheDocument();
  });

  it("shows an em dash for an empty cell", () => {
    render(
      <TableGridView
        tableId="t1"
        canEdit={false}
        columns={[columns[0] as ColumnDef]}
        records={[{ ...records[0], values: {} } as RecordRead]}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("opens the record when a row is clicked", async () => {
    const onOpenRecord = vi.fn();
    const user = userEvent.setup();
    render(
      <TableGridView
        tableId="t1"
        canEdit={false}
        columns={columns}
        records={records}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={onOpenRecord}
      />,
      { wrapper },
    );

    await user.click(screen.getByText("Ada"));

    expect(onOpenRecord).toHaveBeenCalledWith(records[0]);
  });

  it("a text column is sortable and reports the flipped direction", async () => {
    const onSort = vi.fn();
    const user = userEvent.setup();
    render(
      <TableGridView
        tableId="t1"
        canEdit={false}
        columns={columns}
        records={records}
        isLoading={false}
        sort={{ by: "c1", direction: "asc" }}
        onSort={onSort}
        onOpenRecord={vi.fn()}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: "Name" }));

    expect(onSort).toHaveBeenCalledWith({ by: "c1", direction: "desc" });
  });

  it("a multi_select column is not sortable", () => {
    render(
      <TableGridView
        tableId="t1"
        canEdit={false}
        columns={columns}
        records={records}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.queryByRole("button", { name: "Tags" })).not.toBeInTheDocument();
  });

  it("shows the empty state when there are no records", () => {
    render(
      <TableGridView
        tableId="t1"
        canEdit={false}
        columns={columns}
        records={[]}
        isLoading={false}
        sort={{ by: "created_at", direction: "asc" }}
        onSort={vi.fn()}
        onOpenRecord={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByText(/no records yet/i)).toBeInTheDocument();
  });

  describe("editable", () => {
    const second: RecordRead = { ...(records[0] as RecordRead), id: "r2", values: { c1: "Bo" } };

    it("edits a text cell in place and commits it on Enter", async () => {
      vi.mocked(apiClient.patch).mockResolvedValueOnce({ ...records[0], revision: 2 });
      const props = renderEditable();

      fireEvent.click(screen.getAllByRole("button", { name: "Edit Name" })[0] as HTMLElement);
      const input = screen.getByRole("textbox");
      expect(input).toHaveFocus();
      fireEvent.change(input, { target: { value: "Grace" } });
      fireEvent.keyDown(input, { key: "Enter" });

      await waitFor(() =>
        expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
          expected_revision: 1,
          values: { c1: "Grace" },
        }),
      );
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(props.onOpenRecord).not.toHaveBeenCalled();
    });

    it("Escape leaves a cell without writing what was typed", () => {
      renderEditable();

      fireEvent.click(screen.getAllByRole("button", { name: "Edit Name" })[0] as HTMLElement);
      const input = screen.getByRole("textbox");
      fireEvent.change(input, { target: { value: "Grace" } });
      fireEvent.keyDown(input, { key: "Escape" });
      fireEvent.blur(input);

      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(apiClient.patch).not.toHaveBeenCalled();
    });

    it("keeps editing while focus moves inside the cell, and stops when it leaves", () => {
      const notes: ColumnDef = {
        ...(columns[0] as ColumnDef),
        id: "c4",
        label: "Notes",
        type: "long_text",
      };
      renderEditable({ columns: [notes] });

      fireEvent.click(screen.getByRole("button", { name: "Edit Notes" }));
      const area = screen.getByRole("textbox");
      // A plain Enter in a long text is a new line, not the end of the edit.
      fireEvent.keyDown(area, { key: "Enter" });
      fireEvent.blur(area, { relatedTarget: area });
      expect(screen.getByRole("textbox")).toBeInTheDocument();

      fireEvent.blur(area, { relatedTarget: document.body });
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    });

    it("Ctrl+Enter commits a long text", async () => {
      vi.mocked(apiClient.patch).mockResolvedValueOnce({ ...records[0], revision: 2 });
      const notes: ColumnDef = {
        ...(columns[0] as ColumnDef),
        id: "c4",
        label: "Notes",
        type: "long_text",
      };
      renderEditable({ columns: [notes] });

      fireEvent.click(screen.getByRole("button", { name: "Edit Notes" }));
      const area = screen.getByRole("textbox");
      fireEvent.change(area, { target: { value: "line" } });
      fireEvent.keyDown(area, { key: "Enter", ctrlKey: true });

      await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    });

    it("keeps editing while focus is in the cell's own popup", () => {
      renderEditable();
      fireEvent.click(screen.getAllByRole("button", { name: "Edit Name" })[0] as HTMLElement);
      const popup = document.createElement("div");
      popup.setAttribute("role", "listbox");
      const item = document.createElement("button");
      popup.append(item);
      document.body.append(popup);

      fireEvent.blur(screen.getByRole("textbox"), { relatedTarget: item });

      expect(screen.getByRole("textbox")).toBeInTheDocument();
      popup.remove();
    });

    it("flips a yes/no that cannot be empty with one click", async () => {
      vi.mocked(apiClient.patch).mockResolvedValueOnce({ ...records[0], revision: 2 });
      const paid: ColumnDef = {
        ...(columns[0] as ColumnDef),
        id: "c5",
        label: "Paid",
        type: "boolean",
        nullable: false,
      };
      renderEditable({
        columns: [paid],
        records: [{ ...(records[0] as RecordRead), values: { c5: true } }],
      });

      fireEvent.click(screen.getByRole("button", { name: "Edit Paid" }));

      await waitFor(() =>
        expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
          expected_revision: 1,
          values: { c5: false },
        }),
      );
    });

    it("a single choice ends the edit as soon as it is made", async () => {
      vi.mocked(apiClient.patch).mockResolvedValueOnce({ ...records[0], revision: 2 });
      const paid: ColumnDef = {
        ...(columns[0] as ColumnDef),
        id: "c5",
        label: "Paid",
        type: "boolean",
        nullable: true,
      };
      renderEditable({ columns: [paid], records: [{ ...(records[0] as RecordRead), values: {} }] });

      fireEvent.click(screen.getByRole("button", { name: "Edit Paid" }));
      fireEvent.click(screen.getByRole("combobox"));
      fireEvent.click(await screen.findByRole("option", { name: "True" }));

      await waitFor(() =>
        expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
          expected_revision: 1,
          values: { c5: true },
        }),
      );
      await waitFor(() => expect(screen.queryByRole("combobox")).not.toBeInTheDocument());
    });

    it("opens the record with the refused value waiting when a cell write conflicts", async () => {
      vi.mocked(apiClient.patch).mockRejectedValueOnce(conflict409());
      const props = renderEditable();

      fireEvent.click(screen.getAllByRole("button", { name: "Edit Name" })[0] as HTMLElement);
      const input = screen.getByRole("textbox");
      fireEvent.change(input, { target: { value: "Grace" } });
      fireEvent.blur(input);

      await waitFor(() => expect(props.onOpenRecord).toHaveBeenCalledWith(records[0]));
      expect(useTableViewStore.getState().conflicts.r1?.c1?.pendingValues).toEqual({ c1: "Grace" });
    });

    it("leaves any other failed cell write to the hook's toast", async () => {
      vi.mocked(apiClient.patch).mockRejectedValueOnce(new ApiError(500, "boom", null));
      const props = renderEditable();

      fireEvent.click(screen.getAllByRole("button", { name: "Edit Name" })[0] as HTMLElement);
      const input = screen.getByRole("textbox");
      fireEvent.change(input, { target: { value: "Grace" } });
      fireEvent.blur(input);

      await waitFor(() => expect(toast.error).toHaveBeenCalled());
      expect(props.onOpenRecord).not.toHaveBeenCalled();
      expect(useTableViewStore.getState().conflicts).toEqual({});
    });

    it("opens the record from its expand button, not from a row click", async () => {
      const user = userEvent.setup();
      const props = renderEditable();

      await user.click(screen.getByRole("button", { name: "Open record" }));

      expect(props.onOpenRecord).toHaveBeenCalledWith(records[0]);
    });

    it("selects rows one by one or all at once, and clears them", async () => {
      const user = userEvent.setup();
      renderEditable({ records: [records[0] as RecordRead, second] });

      await user.click(screen.getAllByRole("checkbox", { name: "Select row" })[0] as HTMLElement);
      expect(screen.getByText("1 selected")).toBeInTheDocument();
      expect(
        screen.getByRole("checkbox", { name: "Select every row on this page" }),
      ).toHaveAttribute("data-state", "indeterminate");

      await user.click(screen.getByRole("checkbox", { name: "Select every row on this page" }));
      expect(screen.getByText("2 selected")).toBeInTheDocument();

      await user.click(screen.getAllByRole("checkbox", { name: "Select row" })[1] as HTMLElement);
      expect(screen.getByText("1 selected")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Clear" }));
      expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
    });

    it("unselects every row from the header when all are selected", async () => {
      const user = userEvent.setup();
      renderEditable();

      const all = screen.getByRole("checkbox", { name: "Select every row on this page" });
      await user.click(all);
      await user.click(all);

      expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
    });

    it("moves between cells with the arrow keys, and stays put at an edge", async () => {
      const user = userEvent.setup();
      renderEditable({ records: [records[0] as RecordRead, second] });
      const cells = screen.getAllByRole("button", { name: /^Edit / });
      const perRow = cells.length / 2;

      cells[0]!.focus();
      await user.keyboard("{ArrowRight}");
      expect(cells[1]).toHaveFocus();
      await user.keyboard("{ArrowDown}");
      expect(cells[perRow + 1]).toHaveFocus();
      await user.keyboard("{ArrowLeft}{ArrowUp}");
      expect(cells[0]).toHaveFocus();
      await user.keyboard("{ArrowUp}{ArrowLeft}");
      expect(cells[0]).toHaveFocus();
      await user.keyboard("a");
      expect(cells[0]).toHaveFocus();
    });

    it("hands the selected records to the undoable delete, and clears them", async () => {
      const user = userEvent.setup();
      renderEditable({ records: [records[0] as RecordRead, second] });

      await user.click(screen.getByRole("checkbox", { name: "Select every row on this page" }));
      await user.click(screen.getByRole("button", { name: "Delete" }));
      await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));

      expect(deleteLater).toHaveBeenCalledWith([records[0], second]);
      expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
      expect(apiClient.delete).not.toHaveBeenCalled();
    });

    it("puts a menu on each header in place of the sort button, and a + after the last", async () => {
      const onAddColumn = vi.fn();
      const user = userEvent.setup();
      renderEditable({
        columnActions: { onSort: vi.fn(), onRename: vi.fn(), onHide: vi.fn(), onArchive: vi.fn() },
        onAddColumn,
      });

      expect(screen.getByRole("button", { name: "Name column actions" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Name" })).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Add column" }));

      expect(onAddColumn).toHaveBeenCalled();
    });

    it("offers a new-record line under the rows, and none under an empty table", async () => {
      const onAddRecord = vi.fn();
      renderEditable({ onAddRecord });
      expect(screen.getByRole("textbox", { name: /^New record:/ })).toBeInTheDocument();
    });

    it("has no new-record line where records cannot be added", () => {
      renderEditable({ records: [], onAddRecord: vi.fn() });
      expect(screen.queryByRole("textbox", { name: /^New record:/ })).toBeNull();
    });

    it("offers to add a record from the empty state", async () => {
      const onAddRecord = vi.fn();
      const user = userEvent.setup();
      renderEditable({ records: [], onAddRecord });

      expect(
        screen.getByRole("checkbox", { name: "Select every row on this page" }),
      ).toBeDisabled();
      await user.click(screen.getByRole("button", { name: "Add record" }));

      expect(onAddRecord).toHaveBeenCalled();
    });
  });
});
