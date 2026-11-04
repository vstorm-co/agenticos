import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { HiddenColumnsPopover } from "./hidden-columns-popover";
import type { ColumnDef } from "@/types/tables";

const renewal: ColumnDef = {
  id: "c1",
  label: "Renewal",
  type: "date",
  nullable: true,
  default: null,
  options: [],
  archived: false,
};

describe("HiddenColumnsPopover", () => {
  it("shows one hidden column back, or all of them", async () => {
    const user = userEvent.setup();
    const onShow = vi.fn();
    const onShowAll = vi.fn();
    render(<HiddenColumnsPopover hidden={[renewal]} onShow={onShow} onShowAll={onShowAll} />);

    await user.click(screen.getByRole("button", { name: "1 hidden" }));
    await user.click(screen.getByRole("button", { name: "Renewal" }));
    expect(onShow).toHaveBeenCalledWith(renewal);

    await user.click(screen.getByRole("button", { name: "Show all columns" }));
    expect(onShowAll).toHaveBeenCalled();
  });
});
