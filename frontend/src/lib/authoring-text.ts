import type { SuggestionBatch } from "@/types/authoring";

const UUID_REFERENCE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

/** Model prose that contains an identity is replaced by a counted, linked evidence description. */
export function expectedEffect(
  batch: SuggestionBatch,
  fromEvidence: (count: number) => string,
): string {
  const included = batch.hunks.filter((hunk) => hunk.status !== "dismissed");
  if (included.length === 0) return "";
  if (!UUID_REFERENCE.test(batch.expected_effect)) return batch.expected_effect;
  const sources = new Set(included.flatMap((hunk) => hunk.evidence.map((item) => item.run_id)));
  return fromEvidence(sources.size);
}
