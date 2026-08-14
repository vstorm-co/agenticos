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
 * ascending". The accessible name stays the column's own label — the state rides
 * on the `title` here and on `aria-sort` on the `th` DataTable renders — so a
 * test can press "Conversations" rather than the n-th "sorted descending".
 */
function renderButton(props: Parameters<typeof SortButton>[0]) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <SortButton {...props} />
    </NextIntlClientProvider>,
  );
}

describe("SortButton", () => {
  it("answers to the column's label and says it is sortable when sorted by something else", () => {
    renderButton({ active: false, direction: "desc", onClick: vi.fn(), children: "Took" });

    expect(screen.getByRole("button", { name: "Took" })).toHaveAttribute(
      "title",
      messages.ui.sortBy,
    );
  });

  it.each([
    ["asc" as const, messages.ui.sortedAscending],
    ["desc" as const, messages.ui.sortedDescending],
  ])("carries the direction it is sorting in when active: %s", async (direction, title) => {
    renderButton({ active: true, direction, onClick: vi.fn(), children: "Took" });

    expect(screen.getByRole("button", { name: "Took" })).toHaveAttribute("title", title);
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
