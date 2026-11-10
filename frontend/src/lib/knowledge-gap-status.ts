import type { KnowledgeGapStatus } from "@/types/knowledge-gaps";

const STATUSES: readonly KnowledgeGapStatus[] = ["open", "covered", "dismissed"];

/** The status a page's `?status=` names, and the open topics for anything else. */
export function gapStatus(param: string | null): KnowledgeGapStatus {
  return STATUSES.find((status) => status === param) ?? "open";
}
