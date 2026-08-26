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

  it("is named for what it does, not for the shortcut printed on it", () => {
    // The ⌘K hint is decoration for the eye. Left readable it would make the
    // button announce itself as "Search ⌘ K" to a screen reader.
    render(<SidebarSearch />);

    expect(screen.getByRole("button", { name: "search" })).toBeInTheDocument();
    expect(screen.getByText("⌘K")).toHaveAttribute("aria-hidden", "true");
  });
});
