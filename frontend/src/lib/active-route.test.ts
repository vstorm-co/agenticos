import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { isRouteActive, stripLocale, useActiveRoute } from "./active-route";

const path = vi.hoisted(() => ({ current: "/en/agents" as string | null }));
vi.mock("next/navigation", () => ({ usePathname: () => path.current }));

/**
 * Which navigation item is highlighted.
 *
 * Two rules that are easy to get wrong and produce a sidebar that lies: the
 * locale prefix is not part of the route, and `/` and `/dashboard` match exactly
 * because every other path starts with one of them.
 */
describe("stripLocale", () => {
  it("drops a locale this deployment serves", () => {
    expect(stripLocale("/pl/chat")).toBe("/chat");
    expect(stripLocale("/en/agents/a1")).toBe("/agents/a1");
  });

  it("leaves a path that has no locale prefix", () => {
    expect(stripLocale("/dashboard")).toBe("/dashboard");
  });

  it("does not mistake a route segment for a locale", () => {
    // `/kb` is a page, not a language.
    expect(stripLocale("/kb")).toBe("/kb");
  });

  it("reads a bare locale as the root", () => {
    expect(stripLocale("/pl")).toBe("/");
  });

  it("reads an empty path as the root", () => {
    expect(stripLocale("")).toBe("/");
  });
});

describe("isRouteActive", () => {
  it("marks the page somebody is on", () => {
    expect(isRouteActive("/en/agents", "/agents")).toBe(true);
  });

  it("marks the section a sub-page belongs to", () => {
    // Opening one agent has to keep Agents highlighted.
    expect(isRouteActive("/en/agents/a1", "/agents")).toBe(true);
  });

  it("does not mark a section whose name merely starts the same way", () => {
    expect(isRouteActive("/en/agents-archive", "/agents")).toBe(false);
  });

  it("matches the root and the dashboard exactly, because everything starts with them", () => {
    expect(isRouteActive("/en/dashboard", "/dashboard")).toBe(true);
    expect(isRouteActive("/en/dashboard/usage", "/dashboard")).toBe(false);
    expect(isRouteActive("/en", "/")).toBe(true);
    expect(isRouteActive("/en/chat", "/")).toBe(false);
  });

  it("matches exactly when asked to", () => {
    expect(isRouteActive("/en/settings/profile", "/settings", true)).toBe(false);
    expect(isRouteActive("/en/settings", "/settings", true)).toBe(true);
  });

  it("ignores a query string and a fragment on the href", () => {
    // A nav item may carry a default filter; the route is still the route.
    expect(isRouteActive("/en/runs", "/runs?agent=a1")).toBe(true);
    expect(isRouteActive("/en/runs", "/runs#latest")).toBe(true);
  });
});

describe("useActiveRoute", () => {
  it("binds the predicate to the path the router is on", () => {
    path.current = "/en/agents/a1";

    const { result } = renderHook(() => useActiveRoute());

    expect(result.current("/agents")).toBe(true);
    expect(result.current("/agents", true)).toBe(false);
  });

  it("treats a router with no path as the root", () => {
    // Which is what the first render of a static export gets.
    path.current = null;

    const { result } = renderHook(() => useActiveRoute());

    expect(result.current("/")).toBe(true);
  });
});
