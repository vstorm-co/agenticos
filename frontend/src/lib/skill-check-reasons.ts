import type { UnknownReason } from "@/types/skill-checks";

/** Every reason an agent may go unchecked. A reason added to the type fails to compile here. */
const KNOWN: Record<UnknownReason, true> = {
  no_questions: true,
  no_access: true,
  no_budget: true,
  no_published_version: true,
  inconclusive: true,
  failed: true,
  unscorable: true,
  all_evidence: true,
  cancelled: true,
  own_not_asked: true,
  too_few_questions: true,
};

/** Whether the console has words for this reason; one the server added since reads as "other". */
export function knownReason(reason: string): reason is UnknownReason {
  return Object.hasOwn(KNOWN, reason);
}

/** Every reason the console names. */
export const UNKNOWN_REASONS: readonly UnknownReason[] = Object.keys(KNOWN).filter(knownReason);
