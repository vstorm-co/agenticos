import { describe, it, expect } from "vitest";
import { cn, isAppAdmin } from "./utils";

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
