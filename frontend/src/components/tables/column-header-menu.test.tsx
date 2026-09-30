import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ColumnHeaderMenu } from "./column-header-menu";
import type { ColumnDef } from "@/types/tables";

const seats: ColumnDef = {
  id: "c1",
  label: "Seats",
  type: "integer",
  nullable: true,
  default: null,
  options: [],
  archived: false,
};

function actions() {
  return { onSort: vi.fn(), onRename: vi.fn(), onHide: vi.fn(), onArchive: vi.fn() };
}

describe("ColumnHeaderMenu", () => {
  it("shows which way the grid is sorted by this column", () => {
    const { rerender } = render(
      <ColumnHeaderMenu column={seats} sort={{ by: "c1", direction: "asc" }} actions={actions()} />,
    );
    expect(screen.getByRole("button", { name: "Seats column actions" })).toBeInTheDocument();
    rerender(
      <ColumnHeaderMenu
        column={seats}
        sort={{ by: "c1", direction: "desc" }}
        actions={actions()}
      />,
    );
    rerender(
      <ColumnHeaderMenu
        column={seats}
        sort={{ by: "created_at", direction: "asc" }}
        actions={actions()}
      />,
    );
  });

  it.each([
    ["Sort ascending", "onSort", { by: "c1", direction: "asc" }],
    ["Sort descending", "onSort", { by: "c1", direction: "desc" }],
    ["Rename", "onRename", seats],
    ["Hide in this view", "onHide", seats],
    ["Archive column", "onArchive", seats],
  ] as const)("%s", async (item, handler, argument) => {
    const user = userEvent.setup();
    const handlers = actions();
    render(
      <ColumnHeaderMenu
        column={seats}
        sort={{ by: "created_at", direction: "asc" }}
        actions={handlers}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Seats column actions" }));
    await user.click(screen.getByRole("menuitem", { name: item }));

    expect(handlers[handler]).toHaveBeenCalledWith(argument);
  });

  it("offers no sort for a column the service cannot sort", async () => {
    const user = userEvent.setup();
    render(
      <ColumnHeaderMenu
        column={{ ...seats, type: "multi_select" }}
        sort={{ by: "created_at", direction: "asc" }}
        actions={actions()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Seats column actions" }));

    expect(screen.queryByRole("menuitem", { name: "Sort ascending" })).not.toBeInTheDocument();
  });
});
