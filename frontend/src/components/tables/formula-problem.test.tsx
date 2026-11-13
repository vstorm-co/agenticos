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

  it("leaves a reason it does not know, or another failure, to the service's own words", () => {
    const { result } = renderHook(() => useFormulaProblem());
    expect(result.current(refusal("something_new"))).toBeNull();
    expect(result.current(new Error("boom"))).toBeNull();
  });
});
