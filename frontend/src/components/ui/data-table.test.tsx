import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../messages/en.json";
import { DataTable } from "./data-table";

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
