import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api-error";

import { useFormulaProblem } from "./formula-problem";

const refusal = (reason: string, params: Record<string, unknown> = {}) =>
  new ApiError(422, "That is not something a formula can contain", {
    error: {
      code: "INVALID_SCHEMA",
      message: "That is not something a formula can contain",
      details: {
        fields: [{ field: "columns.1.formula", message: "That is not something…" }],
        formula: { reason, params },
      },
    },
  });

describe("useFormulaProblem", () => {
  it("says why a formula was refused from its reason, naming what it names", () => {
    const { result } = renderHook(() => useFormulaProblem());
    expect(result.current(refusal("decimal_comma"))).toEqual({
      field: "columns.1.formula",
      text: "Write decimals with a dot, such as 1.23. A comma separates a function's arguments.",
    });
    expect(result.current(refusal("not_a_value", { label: "Items", type: "link" }))?.text).toBe(
      "{Items} is a link column: a formula reads columns holding values.",
    );
  });

  it("says how many values a function takes when a comma gave it one too many", () => {
    const { result } = renderHook(() => useFormulaProblem());
    expect(
      result.current(refusal("arity", { name: "IF", kind: "exact", fewest: 3, most: 3 }))?.text,
    ).toBe(
      "IF takes 3 values. A comma separates them, so write decimals with a dot, such as 1.23.",
    );
    expect(
      result.current(refusal("arity", { name: "ROUND", kind: "range", fewest: 1, most: 2 }))?.text,
    ).toMatch(/^ROUND takes 1 to 2 values\./);
  });

  it("leaves a reason it does not know, or another failure, to the service's own words", () => {
    const { result } = renderHook(() => useFormulaProblem());
    expect(result.current(refusal("something_new"))).toBeNull();
    expect(result.current(new Error("boom"))).toBeNull();
  });
});
