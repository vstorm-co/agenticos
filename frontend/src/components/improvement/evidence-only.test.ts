import { expect, it } from "vitest";

import { ApiError } from "@/lib/api-error";
import { evidenceOnlyDataset } from "./evidence-only";

function refusal(details: Record<string, unknown>) {
  return new ApiError(400, "Refused", {
    error: { code: "BAD_REQUEST", message: "Refused", details },
  });
}

it("names the dataset only for a refusal about questions taken from the evidence", () => {
  expect(evidenceOnlyDataset(refusal({ dataset_id: "d7", reason: "all_evidence" }))).toBe("d7");
  expect(evidenceOnlyDataset(refusal({ dataset_id: "d7", reason: "only_anonymised" }))).toBeNull();
  expect(evidenceOnlyDataset(refusal({ reason: "all_evidence" }))).toBeNull();
  expect(evidenceOnlyDataset(new Error("Pricing is unavailable"))).toBeNull();
});
