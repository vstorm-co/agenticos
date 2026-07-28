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
vi.mock("@/components/teams", () => ({ OrgSwitcher: () => <button>the org switcher</button> }));
vi.mock("@/components/layout/sidebar-search", () => ({
  SidebarSearch: () => <button>the search row</button>,
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
  it("puts the organization above everything it scopes", () => {
    // Agents, keys and run history are all read through the active
    // organization, and the wrong one selected does not raise an error - it
    // shows a different, equally plausible product. It is not a footer control.
    renderShell();

    const org = screen.getByRole("button", { name: "the org switcher" });
    expect(follows(org, screen.getByRole("navigation"))).toBe(true);
    expect(follows(org, screen.getByRole("button", { name: "the account menu" }))).toBe(true);
  });

  it("puts the account last", () => {
    renderShell();

    const account = screen.getByRole("button", { name: "the account menu" });
    for (const before of ["the org switcher", "the search row", "the theme toggle"]) {
      expect(follows(screen.getByRole("button", { name: before }), account)).toBe(true);
    }
  });

  it("scrolls the destinations without taking the pinned controls with them", () => {
    // The one rule the column cannot break: with enough entries the list moves,
    // and the organization above it and the way out below it do not.
    renderShell();

    const scroller = screen.getByRole("navigation").parentElement;
    expect(scroller).toHaveClass("overflow-y-auto");
    expect(scroller).not.toContainElement(screen.getByRole("button", { name: "the org switcher" }));
    expect(scroller).not.toContainElement(screen.getByRole("button", { name: "the account menu" }));
  });

  it("keeps search and the two settings out of the destination list", () => {
    // Search is an action and the settings are preferences; neither is a place
    // to be, so neither belongs among the links that say where you are.
    renderShell();

    const nav = screen.getByRole("navigation");
    for (const outside of ["the search row", "the language switcher", "the theme toggle"]) {
      expect(nav).not.toContainElement(screen.getByRole("button", { name: outside }));
    }
  });
});
