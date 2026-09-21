import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SidebarShell } from "./sidebar-shell";

/**
 * The blocks are stubbed because this is a test about arrangement, not about
 * their contents - each of those is asserted where it lives. What can go wrong
 * here is positional, and positional mistakes are invisible until the column is
 * full: a long nav that scrolls the organization out of reach, or pushes
 * signing out past the bottom of the screen.
 */
vi.mock("@/components/layout/sidebar-search", () => ({
  SidebarSearch: () => <button>the search row</button>,
}));
vi.mock("@/components/layout/notification-bell", () => ({
  NotificationBell: () => <button>the bell</button>,
}));
vi.mock("@/components/layout/sidebar-user", () => ({
  SidebarUser: () => <button>the account menu</button>,
}));
vi.mock("@/components/language-switcher", () => ({
  LanguageSwitcherIcon: () => <button>the language switcher</button>,
}));
vi.mock("@/components/theme", () => ({ ThemeToggle: () => <button>the theme toggle</button> }));

function renderShell() {
  return render(
    <SidebarShell>
      <nav aria-label="Primary">the destinations</nav>
    </SidebarShell>,
  );
}

function follows(earlier: HTMLElement, later: HTMLElement): boolean {
  return Boolean(earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe("SidebarShell", () => {
  it("opens on the destinations, with nothing above them", () => {
    // The organization moved into the account's menu, so the column starts with
    // the places you can go rather than with the tenant they are read through.
    renderShell();

    const nav = screen.getByRole("navigation");
    for (const below of ["the search row", "the bell", "the account menu"]) {
      expect(follows(nav, screen.getByRole("button", { name: below }))).toBe(true);
    }
  });

  it("puts the account last", () => {
    renderShell();

    const account = screen.getByRole("button", { name: "the account menu" });
    for (const before of ["the search row", "the bell", "the theme toggle"]) {
      expect(follows(screen.getByRole("button", { name: before }), account)).toBe(true);
    }
  });

  it("scrolls the destinations without taking the pinned controls with them", () => {
    // The one rule the column cannot break: with enough entries the list moves,
    // and the strip below it does not.
    renderShell();

    const scroller = screen.getByRole("navigation").parentElement;
    expect(scroller).toHaveClass("overflow-y-auto");
    expect(scroller).not.toContainElement(screen.getByRole("button", { name: "the account menu" }));
    expect(scroller).not.toContainElement(screen.getByRole("button", { name: "the search row" }));
  });

  it("keeps search, the bell and the two settings out of the destination list", () => {
    // Search is an action, the bell is a notice and the settings are
    // preferences; none of them is a place to be, so none belongs among the
    // links that say where you are.
    renderShell();

    const nav = screen.getByRole("navigation");
    for (const outside of [
      "the search row",
      "the bell",
      "the language switcher",
      "the theme toggle",
    ]) {
      expect(nav).not.toContainElement(screen.getByRole("button", { name: outside }));
    }
  });
});
