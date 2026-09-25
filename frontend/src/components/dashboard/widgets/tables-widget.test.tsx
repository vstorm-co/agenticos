import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { TablesWidget } from "./tables-widget";
import type { Period } from "@/lib/dashboard/period";
import type { TableSummary } from "@/types/tables";

const useTablesMock = vi.fn();

vi.mock("@/hooks", () => ({
  useTables: (...args: unknown[]) => useTablesMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-19", to: "2026-08-18" };

function table(overrides: Partial<TableSummary> = {}): TableSummary {
  return {
    id: "t-1",
    name: "Orders",
    description: null,
    visibility: "private",
    owner_user_id: "u-1",
    schema_version: 1,
    archived_at: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
    can_edit: true,
    ...overrides,
  };
}

function renderWidget(
  tables: TableSummary[],
  overrides: Partial<ReturnType<typeof useTablesMock>> = {},
) {
  useTablesMock.mockReturnValue({
    tables,
    total: tables.length,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TablesWidget title="Tables" hint="" period={PERIOD} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  useTablesMock.mockReset();
});

describe("the tables widget", () => {
  it("lists a table by name, linking to its detail page", () => {
    renderWidget([table()]);

    const link = screen.getByRole("link", { name: "Orders" });
    expect(link).toHaveAttribute("href", "/tables/t-1");
  });

  it("asks the server for the six most recently changed tables, rather than re-sorting a name-ordered page", () => {
    // A page of `limit` rows ordered by name (the server's own default) could
    // never contain a table that only happens to sort late - sorting a
    // truncated page after the fact cannot recover what was never fetched.
    renderWidget([table()]);

    expect(useTablesMock).toHaveBeenCalledWith({ sort: "updated_at", limit: 6 });
  });

  it("renders exactly the rows the query answers with, in the order given", () => {
    renderWidget([table({ id: "t-1", name: "First" }), table({ id: "t-2", name: "Second" })]);

    const links = screen.getAllByRole("link").map((link) => link.textContent);
    expect(links).toEqual(["First", "Second"]);
  });

  it("says there are no tables yet, rather than drawing an empty list", () => {
    renderWidget([]);

    expect(screen.getByText("No tables yet")).toBeVisible();
  });

  it("draws a placeholder while the list is being read", () => {
    renderWidget([], { isLoading: true });

    expect(screen.queryByText("No tables yet")).not.toBeInTheDocument();
  });

  it("says the list could not be read, and offers a retry that reaches the query", async () => {
    const refetch = vi.fn();
    renderWidget([], { error: new Error("boom"), refetch });

    expect(screen.queryByText("No tables yet")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledOnce();
  });
});
