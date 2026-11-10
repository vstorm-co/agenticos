import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearCopies,
  COPY_LIMIT,
  copyKey,
  readCopies,
  removeCopy,
  writeCopy,
} from "./unsaved-copies";

afterEach(() => vi.restoreAllMocks());

describe("unsaved copies", () => {
  it("keeps an edit per organization, dataset and place, and reads back only that dataset's", () => {
    vi.useFakeTimers({ now: new Date("2026-10-26T10:00:00Z") });
    writeCopy(copyKey("org-1", "ds-1", "grading"), 3, { a: 1 });
    vi.setSystemTime(new Date("2026-10-26T09:00:00Z"));
    writeCopy(copyKey("org-1", "ds-1", "case:new"), 3, { b: 2 });
    writeCopy(copyKey("org-1", "ds-2", "grading"), 1, {});
    writeCopy(copyKey("org-2", "ds-1", "grading"), 1, {});
    localStorage.setItem("theme", "dark");
    vi.useRealTimers();

    expect(readCopies("org-1", "ds-1")).toEqual([
      {
        key: copyKey("org-1", "ds-1", "case:new"),
        place: "case:new",
        base: 3,
        savedAt: "2026-10-26T09:00:00.000Z",
        value: { b: 2 },
      },
      {
        key: copyKey("org-1", "ds-1", "grading"),
        place: "grading",
        base: 3,
        savedAt: "2026-10-26T10:00:00.000Z",
        value: { a: 1 },
      },
    ]);
  });

  it("skips what does not read as a copy", () => {
    localStorage.setItem(copyKey("o", "d", "broken"), "{not json");
    localStorage.setItem(copyKey("o", "d", "no-base"), JSON.stringify({ savedAt: "x" }));
    localStorage.setItem(copyKey("o", "d", "no-time"), JSON.stringify({ base: 1 }));
    expect(readCopies("o", "d")).toEqual([]);
  });

  it("keeps nothing of an edit too large to keep, and drops its older copy", () => {
    const key = copyKey("o", "d", "grading");
    writeCopy(key, 1, "small");
    writeCopy(key, 1, "x".repeat(COPY_LIMIT));
    expect(localStorage.getItem(key)).toBeNull();
  });

  it("forgets one copy, and every copy at once while leaving the rest of storage", () => {
    writeCopy(copyKey("o", "d", "a"), 1, 1);
    writeCopy(copyKey("o", "d", "b"), 1, 1);
    localStorage.setItem("theme", "dark");
    removeCopy(copyKey("o", "d", "a"));
    expect(readCopies("o", "d").map((copy) => copy.place)).toEqual(["b"]);
    clearCopies();
    expect(readCopies("o", "d")).toEqual([]);
    expect(localStorage.getItem("theme")).toBe("dark");
  });

  it("fails quietly when storage refuses", () => {
    writeCopy(copyKey("o", "d", "grading"), 1, {});
    const refuse = () => {
      throw new Error("blocked");
    };
    vi.spyOn(localStorage, "setItem").mockImplementation(refuse);
    vi.spyOn(localStorage, "removeItem").mockImplementation(refuse);
    vi.spyOn(localStorage, "key").mockImplementation(refuse);
    expect(() => writeCopy("k", 1, {})).not.toThrow();
    expect(() => removeCopy("k")).not.toThrow();
    expect(() => clearCopies()).not.toThrow();
    expect(readCopies("o", "d")).toEqual([]);
  });
});
