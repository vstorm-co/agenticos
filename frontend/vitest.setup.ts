import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

/**
 * How long `findBy*` and `waitFor` keep looking, raised from Testing Library's
 * 1s default.
 *
 * The second deadline in this suite, and the one `testTimeout` cannot cover: a
 * `findByText` that gives up at 1s fails the test at 1s, whatever vitest's
 * limit is. Under the load #862 was filed from it is the deadline that bites
 * most often — two of the three failures in each loaded run, bare and
 * instrumented alike, and the same specs that pass in about a second on a
 * quiet machine.
 *
 * 5s rather than vitest's 15s on purpose: an element that is never coming has
 * to lose the race to `testTimeout`, so the failure reads "Unable to find an
 * element with the text: …" and names it, rather than "Test timed out in
 * 15000ms" and names nothing. It costs nothing when a wait succeeds, which is
 * every passing test — only a genuine failure waits the whole 5s.
 */
configure({ asyncUtilTimeout: 5_000 });

/**
 * Whether this file runs in a browser-shaped environment.
 *
 * Most of the suite does. The route handlers under `src/app/api` declare
 * `@vitest-environment node`, because that is where they actually execute - and
 * everything below that touches `window` has to be skipped for them rather than
 * throwing during setup.
 */
const inBrowser = typeof window !== "undefined";

// Cleanup after each test
afterEach(() => {
  if (!inBrowser) return;
  cleanup();
  localStorage.clear();
});

// Mock Next.js router
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useParams: () => ({}),
  // next-intl's `createNavigation` wraps these at module scope, so a component
  // reaching for locale-aware navigation fails to import at all without them -
  // "No 'redirect' export is defined on the 'next/navigation' mock", from a file
  // that never mentions redirects.
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

// Node 22+ ships built-in localStorage and sessionStorage that are disabled
// (undefined) without --localstorage-file and shadow jsdom's, breaking zustand
// persist and the onboarding resume stash. Provide both.
class StorageMock {
  private store = new Map<string, string>();
  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
}
for (const name of ["localStorage", "sessionStorage"] as const) {
  Object.defineProperty(globalThis, name, {
    configurable: true,
    writable: true,
    value: new StorageMock(),
  });
}
if (inBrowser) {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    writable: true,
    value: globalThis.localStorage,
  });
  Object.defineProperty(window, "sessionStorage", {
    configurable: true,
    writable: true,
    value: globalThis.sessionStorage,
  });

  // Mock matchMedia for responsive components
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

// Observers jsdom does not implement.
//
// Classes rather than `vi.fn().mockImplementation(() => ({...}))`: an arrow
// function is not a constructor, so `new ResizeObserver(...)` threw
// "is not a constructor" the moment a dependency started constructing one
// instead of calling it. Radix's popper and use-size both do, which failed 252
// tests across 41 files on a dependency bump that had nothing to do with them.
class MockResizeObserver implements ResizeObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}

class MockIntersectionObserver implements IntersectionObserver {
  readonly root = null;
  readonly rootMargin = "";
  // Added to the DOM lib in TypeScript 7's `lib.dom.d.ts`. Declared here rather
  // than widened away, so the next field the spec adds fails the type check
  // instead of being silently absent from the mock.
  readonly scrollMargin = "";
  readonly thresholds: readonly number[] = [];
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = vi.fn(() => []);
}

global.ResizeObserver = MockResizeObserver;
global.IntersectionObserver = MockIntersectionObserver;

// Radix's Select drives its trigger with Pointer Events, which jsdom does not
// implement. Without these it throws on the first click, so every test of a
// component containing a Select fails for a reason that has nothing to do with
// the component.
if (inBrowser && !Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}
if (inBrowser && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

/**
 * `useTranslations` backed by the real English catalog.
 *
 * Not a stub returning the key. A component that reads its copy from
 * `messages/en.json` should be testable on what it *says* - "Nothing yet." is the
 * assertion a reader of the test understands, and `t("chat.files.empty")` is not - so
 * the mock builds a real translator over the real catalog with `createTranslator`,
 * ICU and all. A key missing from the catalog therefore fails the test that renders
 * it, which is the property worth having: the guard catches copy that never made it
 * *out* of a component, and this catches a key that never made it *in*.
 *
 * Global rather than per file, because otherwise moving one component onto `t()`
 * means touching every test that renders it. A file that wants the old
 * key-as-value behaviour still mocks `next-intl` itself, and its own mock wins.
 *
 * **One translator per namespace, cached.** The real `useTranslations` is a `useMemo`
 * over stable inputs, so `t` keeps its identity across renders; a mock that built a
 * fresh one per call did not, and a hook putting `t` in a `useCallback`'s dependencies
 * then handed a new function to every render - which an effect keyed on that callback
 * re-fires forever. The admin conversations screen loaded in a loop and never left its
 * spinner (#446). The cache is what makes the mock behave like the thing it stands in
 * for, not a convenience.
 */
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const messages = (await import("./messages/en.json")).default;
  const translators = new Map<string, ReturnType<typeof actual.createTranslator>>();
  return {
    ...actual,
    useLocale: () => "en",
    useMessages: () => messages,
    useFormatter: () => actual.createFormatter({ locale: "en" }),
    useTranslations: (namespace?: string) => {
      const key = namespace ?? "";
      const cached = translators.get(key);
      if (cached !== undefined) return cached;
      const translator = actual.createTranslator({
        locale: "en",
        messages: messages as Parameters<typeof actual.createTranslator>[0]["messages"],
        namespace: namespace as never,
      });
      translators.set(key, translator);
      return translator;
    },
  };
});
