import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api-error";
import { refusedRows } from "./use-dataset-files";

describe("refusedRows", () => {
  const t = (key: string, values: Record<string, string | number>) =>
    `${key}|${Object.values(values).join("|")}`;

  it("names each refused row and field, at most five of them", () => {
    const fields = [
      { field: "rows.2.order_mode", message: "Input should be any" },
      { field: "rows.4", message: "Not a JSON object" },
      { field: "file", message: "ignored" },
      ...[5, 6, 7, 8].map((row) => ({ field: `rows.${row}`, message: "x" })),
    ];
    const refusal = new ApiError(400, "2 rows could not be imported", {
      error: { code: "BAD_REQUEST", message: "refused", details: { fields } },
    });
    expect(refusedRows(refusal, t)?.split("\n")).toEqual([
      "importRowFieldProblem|2|order_mode|Input should be any",
      "importRowProblem|4|Not a JSON object",
      "importRowProblem|5|x",
      "importRowProblem|6|x",
      "importRowProblem|7|x",
    ]);
  });

  it("adds nothing when the refusal names no row", () => {
    expect(refusedRows(new Error("down"), t)).toBeUndefined();
  });
});
