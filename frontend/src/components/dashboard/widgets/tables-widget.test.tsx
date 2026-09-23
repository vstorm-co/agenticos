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

  it("orders tables by most recently updated first", () => {
    renderWidget([
      table({ id: "t-old", name: "Old", updated_at: "2026-08-01T00:00:00Z" }),
      table({ id: "t-new", name: "New", updated_at: "2026-08-15T00:00:00Z" }),
    ]);

    const links = screen.getAllByRole("link").map((link) => link.textContent);
    expect(links).toEqual(["New", "Old"]);
  });

  it("falls back to the creation date when a table has never been updated", () => {
    renderWidget([
      table({
        id: "t-created-later",
        name: "Created later",
        updated_at: null,
        created_at: "2026-08-20T00:00:00Z",
      }),
      table({ id: "t-updated", name: "Updated", updated_at: "2026-08-10T00:00:00Z" }),
    ]);

    const links = screen.getAllByRole("link").map((link) => link.textContent);
    expect(links).toEqual(["Created later", "Updated"]);
  });

  it("falls back to the creation date on either side of the comparison", () => {
    // The sort comparator falls back for each of its two arguments
    // independently - this ordering exercises the fallback on the other one.
    renderWidget([
      table({ id: "t-updated", name: "Updated", updated_at: "2026-08-10T00:00:00Z" }),
      table({
        id: "t-created-later",
        name: "Created later",
        updated_at: null,
        created_at: "2026-08-20T00:00:00Z",
      }),
    ]);

    const links = screen.getAllByRole("link").map((link) => link.textContent);
    expect(links).toEqual(["Created later", "Updated"]);
  });

  it("stops at six rows and leaves the rest to the page", () => {
    renderWidget(
      Array.from({ length: 9 }, (_, index) =>
        table({
          id: `t-${index}`,
          name: `Table ${index}`,
          updated_at: `2026-08-0${(index % 9) + 1}T00:00:00Z`,
        }),
      ),
    );

    expect(screen.getAllByRole("link")).toHaveLength(6);
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
