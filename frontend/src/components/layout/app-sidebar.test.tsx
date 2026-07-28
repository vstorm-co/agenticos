import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NAV_GROUPS, SidebarNav, isActive } from "./app-sidebar";

const can = vi.fn<(permission: string) => boolean>();
const currentPath = vi.fn<() => string>(() => "/dashboard");
const currentUser = vi.fn<() => { role?: string } | null>(() => ({}));

vi.mock("next/navigation", () => ({ usePathname: () => currentPath() }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can }) }));
vi.mock("@/stores", () => ({ useAuthStore: () => ({ user: currentUser() }) }));

function renderNav() {
  return render(<SidebarNav />);
}

describe("isActive", () => {
  it("lights the entry for the page you are on", () => {
    expect(isActive("/agents", "/agents")).toBe(true);
  });

  it("keeps a section lit on its detail pages", () => {
    // Otherwise opening one agent makes the sidebar claim you are nowhere.
    expect(isActive("/agents/abc-123", "/agents")).toBe(true);
  });

  it("keeps a two-letter section lit on its detail pages", () => {
    // The reported bug: the locale prefix used to be stripped by shape rather
    // than by name, so `/kb` was mistaken for a locale and eaten - leaving
    // `/5eacffcc-…`, which is inside nothing. Both the list and the detail page
    // showed a sidebar with no entry lit at all.
    expect(isActive("/kb", "/kb")).toBe(true);
    expect(isActive("/kb/5eacffcc-873e-42fe-a73a-32cd19322d00", "/kb")).toBe(true);
  });

  it("ignores the locale prefix", () => {
    // `/en/agents` and `/agents` are the same page; without this every entry
    // goes dark for anyone not on the default locale.
    expect(isActive("/en/agents", "/agents")).toBe(true);
    expect(isActive("/pl/agents/abc", "/agents")).toBe(true);
    expect(isActive("/pl/kb/abc", "/kb")).toBe(true);
  });

  it("does not light a section on a route that merely starts the same way", () => {
    expect(isActive("/agents-archive", "/agents")).toBe(false);
  });

  it("gives a sub-route to the entry that owns it, not to the one above it", () => {
    // The one case a prefix gets wrong, and the reason the rule is stated once
    // here rather than as a flag every future entry has to remember.
    const hrefs = ["/settings", "/settings/providers"];

    expect(isActive("/settings/providers", "/settings/providers", hrefs)).toBe(true);
    expect(isActive("/settings/providers", "/settings", hrefs)).toBe(false);
    expect(isActive("/settings/providers/openai", "/settings", hrefs)).toBe(false);
  });

  it("returns a sub-route to the entry above once nothing more specific claims it", () => {
    // Deleting the more specific entry must be enough; no second edit.
    expect(isActive("/settings/providers", "/settings", ["/settings"])).toBe(true);
    expect(isActive("/settings/profile", "/settings", ["/settings", "/settings/providers"])).toBe(
      true,
    );
  });
});

describe("SidebarNav", () => {
  it("shows every destination the caller is entitled to", () => {
    can.mockReturnValue(true);

    renderNav();

    for (const label of ["dashboard", "chat", "agents", "skills", "activity"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("hides what the caller's role does not allow", () => {
    // Presentation, not enforcement - but a link that can only refuse them is
    // an invitation to try something that cannot work.
    can.mockImplementation((permission) => permission !== "skills:view");

    renderNav();

    expect(screen.queryByRole("link", { name: "skills" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "agents" })).toBeInTheDocument();
  });

  it("reveals nothing while permissions are still loading", () => {
    // `can()` answers false until they arrive, so the nav fills in rather than
    // briefly offering entries that are about to vanish.
    can.mockReturnValue(false);

    renderNav();

    expect(screen.queryByRole("link", { name: "agents" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "dashboard" })).toBeInTheDocument();
  });

  it("drops a group heading when nothing in it survives the filter", () => {
    // A "Build" label above empty space reads as a broken page.
    can.mockReturnValue(false);

    renderNav();

    expect(screen.queryByText("build")).not.toBeInTheDocument();
  });

  it("keeps the admin group for platform admins only", () => {
    can.mockReturnValue(true);
    currentUser.mockReturnValue({ role: "member" });

    const { unmount } = renderNav();
    expect(screen.queryByRole("link", { name: "adminOverview" })).not.toBeInTheDocument();
    unmount();

    currentUser.mockReturnValue({ role: "admin" });
    renderNav();
    expect(screen.getByRole("link", { name: "adminOverview" })).toBeInTheDocument();
  });

  it("marks the current page for assistive technology", () => {
    can.mockReturnValue(true);
    currentPath.mockReturnValue("/agents");

    renderNav();

    expect(screen.getByRole("link", { name: "agents" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "chat" })).not.toHaveAttribute("aria-current");
  });

  it("runs the caller's callback on navigation, so the drawer can close", () => {
    can.mockReturnValue(true);
    const onNavigate = vi.fn();

    render(<SidebarNav onNavigate={onNavigate} />);
    screen.getByRole("link", { name: "chat" }).click();

    expect(onNavigate).toHaveBeenCalled();
  });
});

describe("the navigation definition", () => {
  const hrefs = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.href));
  const lit = (path: string) => hrefs.filter((href) => isActive(path, href));

  it("lights exactly one entry on every destination it declares", () => {
    // Guards the real table, not a hypothetical one: a new entry that shadows an
    // existing section, or is shadowed by it, fails here rather than in a
    // browser.
    for (const href of hrefs) expect(lit(href), href).toEqual([href]);
  });

  it("lights exactly one entry on a sub-page of every destination", () => {
    for (const href of hrefs) expect(lit(`${href}/1e0a`), href).toEqual([href]);
  });

  it("lights nothing on a page no entry owns", () => {
    // /profile and /billing are reached from the account menu; claiming a
    // section for them would be a lie, not a nicety.
    expect(lit("/profile")).toEqual([]);
    expect(lit("/agents-archive")).toEqual([]);
  });

  it("has no duplicate destinations", () => {
    // Two entries pointing at one page means two of them light up at once.
    const hrefs = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.href));

    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("gives every platform destination a permission to hide behind", () => {
    // Dashboard, Chat and Organizations are open to any member by design;
    // everything else must state what it needs, or a Viewer is shown pages
    // that will refuse them.
    const open = new Set(["dashboard", "chat", "organizations"]);
    const unguarded = NAV_GROUPS.filter((group) => !group.adminOnly)
      .flatMap((group) => group.items)
      .filter((item) => !item.permission && !open.has(item.labelKey));

    expect(unguarded).toEqual([]);
  });
});
