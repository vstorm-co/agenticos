import type { WorkflowLogEntry } from "./types";

/** A node id or a port label as a catalog key: `table.record.upsert` → `table_record_upsert`. */
export function nodeCopyKey(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

/** Custom and legacy log labels retain the words stored at execution time. */
export function logStepName(
  entry: Pick<WorkflowLogEntry, "step_label" | "step_definition_id">,
  t: { (key: string): string; has: (key: string) => boolean },
): string {
  if (!entry.step_definition_id) return entry.step_label;
  const key = `node.${nodeCopyKey(entry.step_definition_id)}.name`;
  return t.has(key) ? t(key) : entry.step_label;
}
