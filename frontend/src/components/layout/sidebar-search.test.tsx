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

  it("is named for what it does, and the row prints no shortcut", () => {
    render(<SidebarSearch />);

    expect(screen.getByRole("button", { name: "search" })).toBeInTheDocument();
    expect(screen.queryByText("⌘K")).not.toBeInTheDocument();
  });

  it("carries its shortcut as a badge in the icon row, the keyboard's own", () => {
    // How anybody learns ⌘K exists; a Mac writes the symbol, the rest name the key.
    const { unmount } = render(<SidebarSearch variant="icon" />);
    expect(screen.getByRole("button", { name: "search" })).toHaveTextContent("searchShortcut");
    unmount();

    const platform = vi.spyOn(navigator, "platform", "get").mockReturnValue("MacIntel");
    render(<SidebarSearch variant="icon" />);
    expect(screen.getByRole("button", { name: "search" })).toHaveTextContent("⌘K");
    platform.mockRestore();
  });
});
