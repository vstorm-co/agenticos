import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_TABLE_DISPLAY, viewColumnKey } from "@/lib/table-display";
import { TABLE_SYSTEM_COLUMNS } from "@/lib/table-system-columns";
import type { ColumnDef, TableDisplay } from "@/types/tables";
import { ViewSettingsPopover } from "./view-settings-popover";

const title: ColumnDef = {
  id: "title",
  label: "Title",
  type: "text",
  nullable: true,
  default: null,
  options: [],
  archived: false,
};
const notes: ColumnDef = { ...title, id: "notes", label: "Notes" };
const columns = [title, notes, ...TABLE_SYSTEM_COLUMNS];
function Harness({
  change,
  toggle,
}: {
  change: (value: TableDisplay) => void;
  toggle: (column: ColumnDef, shown: boolean) => void;
}) {
  const [display, setDisplay] = useState(DEFAULT_TABLE_DISPLAY);
  return (
    <ViewSettingsPopover
      columns={columns}
      visible={null}
      display={display}
      onChange={(next) => {
        setDisplay(next);
        change(next);
      }}
      onToggle={toggle}
    />
  );
}

async function setup() {
  const change = vi.fn();
  const toggle = vi.fn();
  const user = userEvent.setup();
  render(<Harness change={change} toggle={toggle} />);
  await user.click(screen.getByRole("button", { name: "View settings" }));
  return { change, toggle, user };
}

describe("view settings", () => {
  it("reorders visible and system fields with accessible buttons, and resets order", async () => {
    const { change, user } = await setup();
    await user.click(screen.getByRole("button", { name: "Move Notes up" }));
    expect(change).toHaveBeenLastCalledWith(
      expect.objectContaining({
        column_order: ["notes", "title", "created_at", "updated_at", "created_by", "updated_by"],
      }),
    );
    expect(screen.getByRole("button", { name: "Move Notes up" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Move Created up" }));
    expect(change.mock.lastCall?.[0].column_order).toEqual([
      "notes",
      "created_at",
      "title",
      "updated_at",
      "created_by",
      "updated_by",
    ]);
    await user.click(screen.getByRole("button", { name: "Reset order" }));
    expect(change).toHaveBeenLastCalledWith(expect.objectContaining({ column_order: [] }));
  });
  it("hides fields without a schema write and configures wrapping and date/time formats", async () => {
    const { change, toggle, user } = await setup();
    await user.click(screen.getByRole("checkbox", { name: "Show Notes" }));
    expect(toggle).toHaveBeenCalledWith(notes, false);
    await user.click(screen.getByRole("switch", { name: "Wrap text" }));
    expect(change).toHaveBeenLastCalledWith(expect.objectContaining({ wrap_text: true }));
    await user.click(screen.getByRole("combobox", { name: "Date format" }));
    await user.click(screen.getByRole("option", { name: "31.10.2026" }));
    await user.click(screen.getByRole("combobox", { name: "Time format" }));
    await user.click(screen.getByRole("option", { name: "Hide time" }));
    expect(change).toHaveBeenLastCalledWith(
      expect.objectContaining({ date_format: "day_first", time_format: "hidden", wrap_text: true }),
    );
    expect(screen.getByText("Preview: 31.10.2026")).toBeInTheDocument();
  });
  it("also reorders by dropping a grip onto another field", async () => {
    const { change } = await setup();
    fireEvent.dragStart(screen.getByRole("button", { name: "Drag Notes" }), {
      dataTransfer: { setData: vi.fn() },
    });
    fireEvent.drop(
      screen.getByRole("checkbox", { name: "Show Title" }).closest("[data-view-column]")!,
    );
    expect(change.mock.lastCall?.[0].column_order).toEqual([
      "notes",
      ...columns.filter((c) => c.id !== "notes").map(viewColumnKey),
    ]);
  });
});
