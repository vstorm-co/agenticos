import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "../../messages/en.json";
import type { Translate } from "@/lib/agent-step-captions";
import {
  cn,
  EMAIL_RE,
  formatBytes,
  formatDate,
  formatDateTime,
  formatRunDuration,
  getErrorMessage,
  getPasswordStrength,
  isAppAdmin,
  setUrlParam,
  timeAgo,
  truncate,
} from "./utils";

describe("cn utility function", () => {
  it("should merge class names", () => {
    const result = cn("class1", "class2");
    expect(result).toBe("class1 class2");
  });

  it("should handle conditional classes", () => {
    const result = cn("base", { active: true, disabled: false });
    expect(result).toContain("base");
    expect(result).toContain("active");
    expect(result).not.toContain("disabled");
  });

  it("should handle undefined and null values", () => {
    const result = cn("base", undefined, null, "extra");
    expect(result).toBe("base extra");
  });

  it("should merge tailwind classes correctly", () => {
    // tailwind-merge should handle conflicting utilities
    const result = cn("px-2 py-1", "px-4");
    expect(result).toContain("px-4");
    expect(result).toContain("py-1");
  });

  it("should handle empty input", () => {
    const result = cn();
    expect(result).toBe("");
  });

  it("should handle array of classes", () => {
    const result = cn(["class1", "class2"]);
    expect(result).toContain("class1");
    expect(result).toContain("class2");
  });
});

describe("isAppAdmin", () => {
  // The `/admin` surface is hidden on this, and every request behind it is
  // re-checked server-side against the same flag. There used to be a
  // `role === "admin"` fallback here for template deployments that never set it;
  // while it existed the client offered an admin surface whose every request was
  // refused, which reads as a broken product rather than as a missing privilege.
  it("admits the holder of the flag", () => {
    expect(isAppAdmin({ is_app_admin: true })).toBe(true);
  });

  it("refuses somebody without it", () => {
    expect(isAppAdmin({ is_app_admin: false })).toBe(false);
  });

  it("treats an absent flag as not an admin", () => {
    // A persisted auth store can predate the field, so `undefined` has to mean
    // no rather than `undefined === true`.
    expect(isAppAdmin({})).toBe(false);
  });

  it("refuses nobody at all", () => {
    expect(isAppAdmin(null)).toBe(false);
    expect(isAppAdmin(undefined)).toBe(false);
  });

  it("no longer admits anyone on the strength of a role string", () => {
    // `users.role` was dropped in migration 0066. Anything still sending it is
    // sending a field the backend does not have, and it must not decide this.
    expect(isAppAdmin({ role: "admin" } as { is_app_admin?: boolean })).toBe(false);
  });
});

describe("getErrorMessage", () => {
  it("uses the error's own sentence, which is the server's refusal", () => {
    expect(getErrorMessage(new Error("Missing required permission"))).toBe(
      "Missing required permission",
    );
  });

  it("falls back for something thrown that is not an error", () => {
    // A rejected fetch can throw a string or an event; neither is worth showing.
    expect(getErrorMessage("boom")).toBe("An unexpected error occurred");
    expect(getErrorMessage(undefined, "Could not save")).toBe("Could not save");
  });
});

describe("EMAIL_RE", () => {
  it("accepts an address the backend would", () => {
    expect(EMAIL_RE.test("kacper@example.com")).toBe(true);
  });

  it("refuses what is not one", () => {
    // Only the shapes a form can produce by accident: no domain, no local part,
    // no dot, a space in the middle.
    for (const bad of ["kacper@example", "@example.com", "kacper example@a.com", "kacper"]) {
      expect(EMAIL_RE.test(bad), bad).toBe(false);
    }
  });
});

describe("getPasswordStrength", () => {
  it("says nothing about an empty field", () => {
    // The meter appears while somebody types; "Weak" before the first keystroke
    // is a criticism of nothing.
    expect(getPasswordStrength("")).toEqual({ score: 0, label: "", color: "" });
  });

  it("rates a short password weak", () => {
    expect(getPasswordStrength("abc")).toMatchObject({ score: 1, label: "Weak" });
  });

  it("rates a long lowercase password fair", () => {
    expect(getPasswordStrength("abcdefghijkl")).toMatchObject({ score: 2, label: "Fair" });
  });

  it("rates mixed case and length good", () => {
    expect(getPasswordStrength("abcdefghijkL")).toMatchObject({ score: 3, label: "Good" });
  });

  it("rates length, case, a digit and a symbol strong", () => {
    expect(getPasswordStrength("abcdefghijkL1!")).toMatchObject({ score: 4, label: "Strong" });
  });
});

describe("formatBytes", () => {
  it("reads each unit at the precision a person needs", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatBytes(3 * 1024 ** 3)).toBe("3.00 GB");
  });

  it("reads nothing, and a nonsense negative, as zero", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(-1)).toBe("0 B");
  });
});

describe("timeAgo", () => {
  // A fixed now, because the whole function is arithmetic against it.
  const NOW = new Date("2026-07-31T12:00:00Z").getTime();

  afterEach(() => vi.useRealTimers());

  // The real messages, so a broken ICU plural fails here rather than on screen.
  const t = createTranslator({ locale: "en", messages: en, namespace: "time" }) as Translate;

  function at(iso: string): string {
    vi.useFakeTimers({ now: NOW });
    return timeAgo(iso, t);
  }

  it("reads the last minute as just now", () => {
    expect(at("2026-07-31T11:59:30Z")).toBe("just now");
  });

  it("reads minutes, hours and days in the coarsest unit that fits", () => {
    expect(at("2026-07-31T11:30:00Z")).toBe("30m ago");
    expect(at("2026-07-31T09:00:00Z")).toBe("3h ago");
    expect(at("2026-07-29T12:00:00Z")).toBe("2d ago");
  });

  it("falls back to a date once a week has passed", () => {
    // "9d ago" tells nobody anything they could act on.
    expect(at("2026-07-01T12:00:00Z")).toBe("Jul 1");
  });

  it("says nothing for a date it cannot read or one in the future", () => {
    // A clock skew between browser and server produces the second one, and
    // "-3m ago" reads as a bug.
    expect(at("not a date")).toBe("");
    expect(at("2026-08-01T12:00:00Z")).toBe("");
  });
});

describe("formatDate", () => {
  it("reads a date, from a string or a Date", () => {
    expect(formatDate("2026-07-31T12:00:00Z", "en")).toBe("Jul 31, 2026");
    expect(formatDate(new Date("2026-07-31T12:00:00Z"), "en")).toBe("Jul 31, 2026");
  });

  it("formats in the active locale, not en-US", () => {
    // Month name and day-month order come from the runtime, so the locale has
    // to reach the formatter - under `pl` this read "Jul 31, 2026" before #649.
    expect(formatDate("2026-07-31T12:00:00Z", "pl")).toBe("31 lip 2026");
  });

  it("says nothing rather than 'Invalid Date' for what it cannot read", () => {
    // Which is what a listing shows for a row whose timestamp the API omitted.
    expect(formatDate(null, "en")).toBe("-");
    expect(formatDate(undefined, "en")).toBe("-");
    expect(formatDate("", "en")).toBe("-");
    expect(formatDate("not a date", "en")).toBe("-");
  });
});

describe("formatDateTime", () => {
  it("reads a timestamp down to the minute", () => {
    expect(formatDateTime("2026-07-31T12:34:00Z", "en")).toMatch(/Jul 31, 2026/);
    expect(formatDateTime(new Date("2026-07-31T12:34:00Z"), "en")).toMatch(/Jul 31, 2026/);
  });

  it("formats in the active locale, not en-US", () => {
    expect(formatDateTime("2026-07-31T12:34:00Z", "pl")).toMatch(/31 lip 2026/);
  });
});

describe("formatRunDuration", () => {
  it("reports sub-second runs in milliseconds and longer ones in seconds", () => {
    expect(formatRunDuration("2026-08-04T09:00:00.000Z", "2026-08-04T09:00:00.850Z")).toBe(
      "850 ms",
    );
    expect(formatRunDuration("2026-08-04T09:00:00Z", "2026-08-04T09:00:01.400Z")).toBe("1.4 s");
    expect(formatRunDuration("2026-08-04T09:00:00Z", "2026-08-04T09:00:30Z")).toBe("30 s");
  });

  it("admits it does not know a duration when the run has not finished", () => {
    // A null end is not a fast run: a still-running or parked run has no duration
    // yet, and rendering "0 ms" would call the unfinished the fastest.
    expect(formatRunDuration("2026-08-04T09:00:00Z", null)).toBe("-");
    expect(formatRunDuration(null, "2026-08-04T09:00:30Z")).toBe("-");
  });

  it("refuses a negative or unparsable window rather than printing nonsense", () => {
    expect(formatRunDuration("2026-08-04T09:00:30Z", "2026-08-04T09:00:00Z")).toBe("-");
    expect(formatRunDuration("2026-08-04T09:00:00Z", "not a date")).toBe("-");
  });
});

describe("truncate", () => {
  it("leaves what already fits", () => {
    expect(truncate("short", 10)).toBe("short");
  });

  it("cuts to the length including the ellipsis, not beyond it", () => {
    expect(truncate("abcdefghij", 8)).toBe("abcde...");
  });
});

describe("setUrlParam", () => {
  it("writes a filter into the address bar without navigating", () => {
    // The point of it: a filtered list is a link somebody can send.
    window.history.replaceState({}, "", "/runs");

    setUrlParam("agent", "a1");

    expect(window.location.search).toBe("?agent=a1");
  });

  it("drops the parameter rather than writing an empty one", () => {
    window.history.replaceState({}, "", "/runs?agent=a1");

    setUrlParam("agent", null);

    expect(window.location.search).toBe("");
  });
});
