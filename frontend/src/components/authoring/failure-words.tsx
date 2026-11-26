"use client";

import { useTranslations } from "next-intl";

import { NativeDisclosure } from "@/components/ui/native-disclosure";
import type { AuthoringFailure, AuthoringRequest, StepFailure } from "@/types/authoring";
import type { ImprovementFailure } from "@/types/improvement";

/** The counts each code's sentence names; a code sent without them is shown as stored. */
const STEP: Record<StepFailure, readonly string[]> = {
  system_agent_not_seeded: [],
  system_agent_missing: [],
  system_agent_unpublished: [],
  system_agent_archived: [],
  system_agent_no_access: [],
  system_agent_no_model: [],
  system_agent_failed: [],
  only_anonymised: [],
  all_evidence: [],
  no_scorer: [],
  no_reruns: [],
  evidence_too_large: [],
  budget: [],
  not_found: [],
  not_allowed: [],
  changed: [],
  run_failed: [],
  refused: [],
  failed: [],
};

const SESSION: Record<Exclude<ImprovementFailure, StepFailure>, readonly string[]> = {
  too_few_held_out: ["missing"],
  no_evidence: [],
  search_too_few_training: ["minimum"],
};

const REQUEST: Record<Exclude<AuthoringFailure, StepFailure>, readonly string[]> = {
  no_runs_view: [],
  evidence_erased: [],
  no_edit_agent: [],
  agent_gone: [],
  no_published_version: [],
  skill_gone: [],
  no_edit_skill: [],
  session_moved_on: [],
  conflicts_unanswered: [],
  session_stopped: [],
  context_gone: [],
  no_edit_context: [],
  unknown_skill_use: ["runs"],
  no_evidence: [],
  key_revoked: [],
  not_a_member: [],
  unexpected: [],
  stalled: [],
  withdrawn: [],
};

const SHARED = new Map(Object.entries(STEP));
const OWN = {
  session: new Map(Object.entries(SESSION)),
  request: new Map(Object.entries(REQUEST)),
};

/** A failure as a session or an assistant request stores it. */
export interface StoredFailure {
  error: string | null;
  error_code?: string | null;
  error_params?: Record<string, number> | null;
}

export interface FailureWords {
  /** The failure in the reader's language, or as stored for a code this console does not know. */
  text: string | null;
  /**
   * The stored English, for a code taken from a refusal: its sentence is the one place
   * that names which agent or dataset the refusal was about.
   */
  detail: string | null;
}

/** Words a stored failure of a session or a request in the reader's language. */
export function useFailureWords(
  of: "session" | "request",
): (failure: StoredFailure) => FailureWords {
  const t = useTranslations("stepFailure");
  return (failure) => {
    const code = failure.error_code ?? "";
    const params = failure.error_params ?? {};
    const shared = SHARED.get(code);
    const counts = shared ?? OWN[of].get(code);
    if (!counts || !counts.every((name) => typeof params[name] === "number")) {
      return { text: failure.error, detail: null };
    }
    if (shared) return { text: t(`step.${code}`, params), detail: failure.error };
    return {
      text: of === "session" ? t(`session.${code}`, params) : t(`request.${code}`, params),
      detail: null,
    };
  };
}

/** Why an assistant request failed, with the stored English under Technical details when it names more. */
export function RequestFailure({
  request,
  className,
}: {
  request: AuthoringRequest;
  className: string;
}) {
  const t = useTranslations("stepFailure");
  const words = useFailureWords("request")(request);
  return (
    <>
      <p role="alert" className={className}>
        {words.text}
      </p>
      {words.detail && (
        <NativeDisclosure className="text-muted-foreground text-xs">
          <summary className="cursor-pointer">{t("technicalDetails")}</summary>
          <p lang="en" className="mt-1 break-words">
            {words.detail}
          </p>
        </NativeDisclosure>
      )}
    </>
  );
}
