import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SidebarSearch } from "./sidebar-search";

vi.mock("next-intl", async () => ({
  useTranslations: (await import("@/test-utils/intl")).keyTranslations(),
}));

describe("SidebarSearch", () => {
  it("opens the command palette rather than searching anything itself", () => {
    // The whole point of the row: one search in the product, reached from the
    // column and from ⌘K. A second implementation would be a second set of
    // results to keep correct.
    const opened = vi.fn();
    window.addEventListener("command-palette:open", opened);

    render(<SidebarSearch />);
    screen.getByRole("button").click();

    expect(opened).toHaveBeenCalledOnce();
    window.removeEventListener("command-palette:open", opened);
  });

  it("is named for what it does, and prints no shortcut", () => {
    // The ⌘K chip is gone from both variants. It taught the shortcut once and
    // then sat in the column forever, and in the icon row it made search the
    // one control wider than every other single-icon button beside it. The
    // palette still opens on ⌘K and still says so on its own placeholder,
    // which is where the reminder can actually be used.
    render(<SidebarSearch />);

    expect(screen.getByRole("button", { name: "search" })).toBeInTheDocument();
    expect(screen.queryByText("⌘K")).not.toBeInTheDocument();
  });

  it("is a square button in the icon row, the size of the bell beside it", () => {
    const { container } = render(<SidebarSearch variant="icon" />);

    expect(container.querySelector("button")).toHaveClass("w-9", "h-9");
  });
});
