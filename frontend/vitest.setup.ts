import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

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
}));

// Node 22+ ships a built-in localStorage that is disabled (undefined) without
// --localstorage-file and shadows jsdom's, breaking zustand persist. Provide one.
class LocalStorageMock {
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
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  writable: true,
  value: new LocalStorageMock(),
});
if (inBrowser) {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    writable: true,
    value: globalThis.localStorage,
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
