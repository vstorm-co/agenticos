import type { WorkflowMediaOperationRead } from "@/lib/workflows/types";

export function makeMediaOperation(
  patch: Partial<WorkflowMediaOperationRead> = {},
): WorkflowMediaOperationRead {
  return {
    operation_id: "operation-a",
    phase: "unknown",
    held_usd: "0.50",
    incurred_usd: "0.02",
    booked_usd: "0.01",
    cost_source: "catalog_estimate",
    accounting_complete: false,
    node_unresolved_usd: "0.70",
    has_receipt: false,
    retry_effect: "reconciliation_required",
    ...patch,
  };
}
