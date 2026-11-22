import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useRouter } from "./locale-navigation";
import { NAVIGATION_START } from "./navigation-progress";

const locale = vi.hoisted(() => ({
  path: vi.fn(),
  router: { push: vi.fn(), replace: vi.fn(), back: vi.fn() },
}));
vi.mock("next-intl/navigation", () => ({
  createNavigation: () => ({
    getPathname: locale.path,
    usePathname: () => "/chat",
    useRouter: () => locale.router,
  }),
}));
afterEach(() => vi.restoreAllMocks());

it("announces a language change using its resolved URL without altering locale router arguments", () => {
  window.history.replaceState({}, "", "/chat");
  locale.path.mockReturnValue("/pl/chat");
  const events = vi.spyOn(window, "dispatchEvent");
  const { result } = renderHook(useRouter);
  act(() => result.current.replace("/chat", { locale: "pl", scroll: false }));
  expect(locale.path).toHaveBeenCalledWith({ href: "/chat", locale: "pl" });
  expect(locale.router.replace).toHaveBeenCalledWith("/chat", { locale: "pl", scroll: false });
  expect(events.mock.calls[0]?.[0].type).toBe(NAVIGATION_START);
});

// The T3 fork serves English only: a retired locale prefix (`/pl`) is never carried
// into navigation, so every resolved href uses the default locale.
it("resolves object hrefs in the default English locale, ignoring a retired locale prefix", () => {
  window.history.replaceState({}, "", "/pl/chat");
  locale.path.mockReturnValue("/pl/projects?team=one");
  const { result, rerender } = renderHook(useRouter);
  const href = { pathname: "/projects", query: { team: "one" } };
  act(() => result.current.push(href));
  expect(locale.path).toHaveBeenLastCalledWith({ href, locale: "en" });
  expect(locale.router.push).toHaveBeenCalledWith(href);
  expect(result.current.back).toBe(locale.router.back);
  const first = result.current;
  rerender();
  expect(result.current).toBe(first);
  window.history.replaceState({}, "", "/chat");
  locale.path.mockReturnValue("/projects");
  act(() => result.current.push("/projects"));
  expect(locale.path).toHaveBeenLastCalledWith({ href: "/projects", locale: "en" });
});

it("does not start progress for replacing the same page", () => {
  window.history.replaceState({}, "", "/pl/chat");
  locale.path.mockReturnValue("/pl/chat");
  const events = vi.spyOn(window, "dispatchEvent");
  const { result } = renderHook(useRouter);
  act(() => result.current.replace("/chat"));
  expect(locale.path).toHaveBeenLastCalledWith({ href: "/chat", locale: "en" });
  expect(events).not.toHaveBeenCalled();
  window.history.replaceState({}, "", "/chat");
  locale.path.mockReturnValue("/projects");
  act(() => result.current.replace("/projects"));
  expect(locale.path).toHaveBeenLastCalledWith({ href: "/projects", locale: "en" });
  expect(events.mock.calls[0]?.[0].type).toBe(NAVIGATION_START);
});
