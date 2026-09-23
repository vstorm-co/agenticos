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
  SidebarUser: ({ compact }: { compact?: boolean }) => (
    <button>{compact ? "the account avatar" : "the account menu"}</button>
  ),
}));
vi.mock("@/components/language-switcher", () => ({
  LanguageSwitcherIcon: () => <button>the language switcher</button>,
}));
vi.mock("@/components/theme", () => ({ ThemeToggle: () => <button>the theme toggle</button> }));

function renderShell(props: { collapsed?: boolean } = {}) {
  return render(
    <SidebarShell collapsed={props.collapsed}>
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
    for (const below of ["the search row", "the account menu"]) {
      expect(follows(nav, screen.getByRole("button", { name: below }))).toBe(true);
    }
  });

  it("puts the account last", () => {
    renderShell();

    const account = screen.getByRole("button", { name: "the account menu" });
    for (const before of ["the search row", "the bell"]) {
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

  it("keeps the actions out of the destination list", () => {
    // Search is an action and the bell is a notice; neither is a place to be,
    // so neither belongs among the links that say where you are.
    renderShell();

    const nav = screen.getByRole("navigation");
    for (const outside of ["the search row", "the bell"]) {
      expect(nav).not.toContainElement(screen.getByRole("button", { name: outside }));
    }
  });

  it("carries search and the bell at both widths", () => {
    // They are the footer's only two controls now - the language and the theme
    // are named rows in the account menu, where somebody looks for a setting.
    for (const collapsed of [false, true]) {
      const view = renderShell({ collapsed });
      expect(screen.getByRole("button", { name: "the search row" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "the bell" })).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "the language switcher" }),
      ).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "the theme toggle" })).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("hands the account its compact shape on the rail", () => {
    renderShell({ collapsed: true });

    expect(screen.getByRole("button", { name: "the account avatar" })).toBeInTheDocument();
  });

  it("draws no collapse control, which belongs on the column's own title bar", () => {
    // `AppSidebar` puts it beside the brand. The slide-over has no equivalent
    // and needs none: a drawer somebody opened on purpose has the width.
    renderShell();

    expect(screen.queryByRole("button", { name: "the collapse control" })).not.toBeInTheDocument();
  });
});
