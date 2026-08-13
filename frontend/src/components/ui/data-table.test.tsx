import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { DataTable, type Column } from "./data-table";

/**
 * The state this file exists for is **failed, not empty**.
 *
 * Every page in this product fans out to several queries and drew its empty state
 * when one of them failed, so "no runs yet" and "the request answered 502" were
 * the same pixels - a live defect on `/rag` (#32). A reassuring sentence in place
 * of an error is worse than no page at all, because nobody goes looking.
 */
interface Row {
  id: string;
  name: string;
}

function renderTable(props: Partial<Parameters<typeof DataTable<Row>>[0]> = {}) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <DataTable<Row>
        columns={[{ key: "name", header: "Name", cell: (row) => row.name }]}
        rows={[]}
        getRowKey={(row) => row.id}
        {...props}
      />
    </NextIntlClientProvider>,
  );
}

describe("DataTable", () => {
  it("draws the rows it was given", () => {
    renderTable({ rows: [{ id: "1", name: "Billing clerk" }] });

    expect(screen.getByText("Billing clerk")).toBeInTheDocument();
  });

  it("says nothing is here when nothing is here", () => {
    renderTable({ rows: [], empty: "No runs yet" });

    expect(screen.getByText("No runs yet")).toBeInTheDocument();
  });

  it("shows the failure instead of the empty state when the request failed", () => {
    renderTable({ rows: [], empty: "No runs yet", error: "Could not load runs" });

    expect(screen.getByRole("alert")).toHaveTextContent("Could not load runs");
    expect(screen.queryByText("No runs yet")).not.toBeInTheDocument();
  });

  // A refetch that fails leaves the previous page in `rows`. Drawing those with no
  // warning tells a reader they are looking at current data.
  it("shows the failure even when rows arrived before it", () => {
    renderTable({ rows: [{ id: "1", name: "Billing clerk" }], error: "Could not load runs" });

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  // The shape a failed query actually leaves behind: not an empty array but no
  // array at all, because the hook's `data` is null. `showEmpty` requires rows to
  // be one, so a caller who folded the refusal into `empty` rendered *neither* -
  // a header row over nothing at all, which is how the ratings page reported a
  // 502 and why this is a prop rather than something a caller remembers.
  it("shows the failure when the request left no rows behind at all", () => {
    renderTable({ rows: undefined, empty: "No ratings found", error: "Could not load ratings" });

    expect(screen.getByRole("alert")).toHaveTextContent("Could not load ratings");
    expect(screen.queryByText("No ratings found")).not.toBeInTheDocument();
  });

  it("says neither while it is still loading", () => {
    renderTable({ rows: undefined, loading: true, empty: "No runs yet", error: "Failed" });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("No runs yet")).not.toBeInTheDocument();
  });

  it("falls back to its own wording when a caller names no empty state", () => {
    renderTable({ rows: [] });

    expect(screen.getByText(messages.ui.noResults)).toBeInTheDocument();
  });
});

interface Run {
  id: string;
  name: string;
  seconds: number | null;
}

const runColumns: Column<Run>[] = [
  {
    key: "name",
    header: "Name",
    cell: (row) => row.name,
    sortable: true,
    sortValue: (row) => row.name,
  },
  {
    key: "seconds",
    header: "Took",
    cell: (row) => String(row.seconds),
    sortable: true,
    sortValue: (row) => row.seconds,
  },
];

const runs: Run[] = [
  { id: "1", name: "billing", seconds: 4 },
  { id: "2", name: "answers", seconds: 9 },
  { id: "3", name: "parked", seconds: null },
];

function rowNames() {
  const body = screen.getAllByRole("rowgroup")[1]!;
  return within(body)
    .getAllByRole("row")
    .map((row) => within(row).getAllByRole("cell")[0]!.textContent);
}

function renderRuns(props: Partial<Parameters<typeof DataTable<Run>>[0]> = {}) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <DataTable<Run> columns={runColumns} rows={runs} getRowKey={(row) => row.id} {...props} />
    </NextIntlClientProvider>,
  );
}

describe("DataTable client-side sorting", () => {
  it("sorts the rows it holds when a sortable header is pressed, descending first", async () => {
    const user = userEvent.setup();
    renderRuns();

    await user.click(screen.getByRole("button", { name: "Name" }));

    expect(rowNames()).toEqual(["parked", "billing", "answers"]);
  });

  it("flips the direction when the same header is pressed again", async () => {
    const user = userEvent.setup();
    renderRuns();

    const header = screen.getAllByRole("button")[0]!;
    await user.click(header);
    await user.click(header);

    expect(rowNames()).toEqual(["answers", "billing", "parked"]);
  });

  it("sorts a row without a value last in both directions", async () => {
    const user = userEvent.setup();
    renderRuns({ defaultSort: { by: "seconds", dir: "desc" } });

    expect(rowNames()).toEqual(["answers", "billing", "parked"]);

    await user.click(screen.getAllByRole("button")[1]!);

    expect(rowNames()).toEqual(["billing", "answers", "parked"]);
  });

  it("marks the sorted column for a screen reader", () => {
    renderRuns({ defaultSort: { by: "name", dir: "asc" } });

    expect(screen.getAllByRole("columnheader")[0]!).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getAllByRole("columnheader")[1]!).not.toHaveAttribute("aria-sort");
  });
});

describe("DataTable server-side sorting", () => {
  it("asks the caller instead of touching the rows, a new column starting descending", async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    renderRuns({ onSort, sort: { by: "name", dir: "desc" } });

    await user.click(screen.getAllByRole("button")[1]!);

    expect(onSort).toHaveBeenCalledWith({ by: "seconds", dir: "desc" });
    expect(rowNames()).toEqual(["billing", "answers", "parked"]);
  });

  it("hands back the flipped direction for the column already sorted", async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    renderRuns({ onSort, sort: { by: "name", dir: "desc" } });

    await user.click(screen.getAllByRole("button")[0]!);

    expect(onSort).toHaveBeenCalledWith({ by: "name", dir: "asc" });
  });
});

describe("DataTable filters", () => {
  const filterable: Column<Run>[] = [
    {
      key: "name",
      header: "Name",
      cell: (row) => row.name,
      filter: "text",
      filterValue: (row) => row.name,
    },
    {
      key: "seconds",
      header: "Took",
      cell: (row) => String(row.seconds),
      filter: "select",
      filterOptions: [
        { value: "4", label: "four" },
        { value: "9", label: "nine" },
      ],
      filterValue: (row) => String(row.seconds),
    },
  ];

  it("narrows the rows it holds to what a text filter matches", async () => {
    const user = userEvent.setup();
    renderRuns({ columns: filterable });

    await user.type(screen.getByRole("textbox", { name: messages.ui.filterColumn }), "bill");

    expect(rowNames()).toEqual(["billing"]);
  });

  it("narrows to an exact match on a select filter", async () => {
    const user = userEvent.setup();
    renderRuns({ columns: filterable });

    await user.selectOptions(screen.getByRole("combobox", { name: messages.ui.filterColumn }), "9");

    expect(rowNames()).toEqual(["answers"]);
  });

  it("shows the empty state when a filter matches nothing", async () => {
    const user = userEvent.setup();
    renderRuns({ columns: filterable, empty: "Nothing matches" });

    await user.type(screen.getByRole("textbox", { name: messages.ui.filterColumn }), "zzz");

    expect(screen.getByText("Nothing matches")).toBeInTheDocument();
  });

  it("asks the caller instead when the server filters", async () => {
    const user = userEvent.setup();
    const onFilter = vi.fn();
    renderRuns({ columns: filterable, onFilter, filters: {} });

    await user.type(screen.getByRole("textbox", { name: messages.ui.filterColumn }), "b");

    expect(onFilter).toHaveBeenCalledWith("name", "b");
    expect(rowNames()).toEqual(["billing", "answers", "parked"]);
  });
});
