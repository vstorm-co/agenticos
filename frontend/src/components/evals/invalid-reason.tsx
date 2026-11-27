"use client";

import { useTranslations } from "next-intl";

import type { EvalComparison, InvalidReasonCode } from "@/types/eval-runs";

/**
 * Every reason the console words itself, with the numbers its words need. A code
 * added to the type fails to compile here.
 */
const WORDED: Record<InvalidReasonCode, readonly string[]> = {
  knowledge_not_retrieved: [],
  too_few_held_out: ["missing"],
  scoring_changed: [],
  judge_changed_mid_run: [],
  judge_instructions_changed: [],
  judge_differs: [],
  knowledge_draft_changed: [],
  held_out_ungraded: [],
};

type Reason = Pick<
  EvalComparison,
  "invalid_reason" | "invalid_reason_code" | "invalid_reason_params"
>;

/**
 * Why two sides cannot be compared, in the reader's language. A code this console
 * does not know yet, or a reason with no code, reads as the server's English sentence.
 */
export function InvalidReason({
  comparison,
  className,
}: {
  comparison: Reason;
  className?: string;
}) {
  const t = useTranslations("evals.invalidReason");
  const code = comparison.invalid_reason_code;
  const params = comparison.invalid_reason_params ?? {};
  // A server that sent the code without its numbers is read in its own English.
  const worded =
    code && Object.hasOwn(WORDED, code) && WORDED[code].every((name) => name in params);
  const text = worded ? t(code, params) : comparison.invalid_reason;
  return text ? <p className={className}>{text}</p> : null;
}
