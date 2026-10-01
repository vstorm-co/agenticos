import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ColumnDef, TableListItem } from "@/types/tables";

import { OptionChip, selectChips } from "./option-chip";
import { TableCard } from "./table-card";

const TABLE: TableListItem = {
  id: "t",
  name: "Leads",
  description: null,
  visibility: "team",
  owner_user_id: null,
  schema_version: 3,
  archived_at: null,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: null,
  can_edit: false,
  record_count: 14,
  column_count: 1,
};

describe("TableCard", () => {
  it("shows how much a table holds, who may reach it, and that this caller only reads it", () => {
    render(<TableCard table={TABLE} />);
    expect(screen.getByRole("link", { name: "Open Leads" })).toHaveAttribute("href", "/tables/t");
    expect(screen.getByText("14 records · 1 column")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Team" })).toBeTruthy();
    expect(screen.getByText("Read only")).toBeTruthy();
    expect(screen.getByText(/^edited /)).toBeTruthy();
    // No description, and none said to be missing.
    expect(screen.queryByText("No description yet.")).toBeNull();
  });

  it("says what a table is for when it says so", () => {
    render(<TableCard table={{ ...TABLE, description: "Inbound leads", can_edit: true }} />);
    expect(screen.getByText("Inbound leads")).toBeTruthy();
    expect(screen.queryByText("Read only")).toBeNull();
  });
});

const STAGE: ColumnDef = {
  id: "c",
  label: "Stage",
  type: "single_select",
  nullable: true,
  default: null,
  archived: false,
  options: [
    { id: "o1", label: "New", archived: false },
    { id: "o2", label: "Won", archived: true },
  ],
};

describe("option chips", () => {
  it("shows a select value by its option's label, an archived one struck through", () => {
    render(
      <>
        <OptionChip column={STAGE} optionId="o1" />
        <OptionChip column={STAGE} optionId="o2" />
        <OptionChip column={STAGE} optionId="gone" />
      </>,
    );
    expect(screen.getByText("New")).toBeTruthy();
    expect(screen.getByText("Won").className).toContain("line-through");
    expect(screen.getByText("gone")).toBeTruthy();
  });

  it("renders a single or a multi select as chips, and nothing else", () => {
    const multi: ColumnDef = { ...STAGE, type: "multi_select" };
    const { container } = render(<>{selectChips(multi, ["o1", 7, "o2"])}</>);
    expect(container.textContent).toBe("NewWon");
    expect(selectChips(STAGE, "o1")).not.toBeNull();
    expect(selectChips(multi, [])).toBeNull();
    expect(selectChips({ ...STAGE, type: "text" }, "o1")).toBeNull();
  });
});
