import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { SortButton } from "./sort-button";

/**
 * The sort control two pages need, which is why it is in `ui/` rather than a
 * second copy. It had been a local component inside `admin/conversations`.
 *
 * The state worth testing is the *third* one: a column that can be sorted but is
 * not currently sorting. Without it a reader cannot tell "sortable" from "sorted
 * ascending", and the accessible name is the only thing that carries the
 * difference to anybody not looking at the arrow.
 */
function renderButton(props: Parameters<typeof SortButton>[0]) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <SortButton {...props} />
    </NextIntlClientProvider>,
  );
}

describe("SortButton", () => {
  it("says it is sortable when the table is sorted by something else", () => {
    renderButton({ active: false, direction: "desc", onClick: vi.fn(), children: "Took" });

    expect(screen.getByRole("button", { name: messages.ui.sortBy })).toBeInTheDocument();
  });

  it.each([
    ["asc" as const, messages.ui.sortedAscending],
    ["desc" as const, messages.ui.sortedDescending],
  ])("names the direction it is sorting in when active: %s", async (direction, name) => {
    renderButton({ active: true, direction, onClick: vi.fn(), children: "Took" });

    expect(screen.getByRole("button", { name })).toBeInTheDocument();
  });

  it("keeps the column's own label alongside that", () => {
    renderButton({ active: true, direction: "asc", onClick: vi.fn(), children: "Took" });

    expect(screen.getByRole("button")).toHaveTextContent("Took");
  });

  it("asks the caller to decide what the next order is", async () => {
    const onClick = vi.fn();
    renderButton({ active: true, direction: "asc", onClick, children: "Took" });

    await userEvent.click(screen.getByRole("button"));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
