"use client";

import { Ban } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui";
import type { AgentCeiling } from "@/types/agents";

/** What a disabled create control names as its reason, via `aria-describedby`. */
export const AGENT_LIMIT_NOTICE_ID = "agent-limit-notice";

/**
 * Whether a create would be refused for the organization's agent limit (#2488).
 *
 * The server's `at_limit`, not a comparison here: a caller who cannot see every
 * agent gets no count to compare. The refusal stays the guarantee; this only
 * lets the console say so before a form is filled in rather than after it is sent.
 */
export function isAtAgentLimit(
  ceiling: AgentCeiling | null,
): ceiling is AgentCeiling & { limit: number } {
  return ceiling !== null && ceiling.at_limit && ceiling.limit !== null;
}

/**
 * Why no agent can be created here, and the two ways out of it.
 *
 * `id` is for the one notice a disabled control points at; a second copy (the
 * template dialog's) goes without, so the page never holds the id twice.
 */
export function AgentLimitNotice({
  ceiling,
  id,
}: {
  ceiling: AgentCeiling & { limit: number };
  id?: string;
}) {
  const t = useTranslations("agentLimit");
  return (
    // A standing explanation, not an interruption: `status` rather than the
    // primitive's `alert`, which a screen reader would announce on every load.
    <Alert id={id} variant="warning" role="status">
      <Ban className="h-4 w-4" />
      <AlertTitle>{t("title")}</AlertTitle>
      <AlertDescription>
        {/* No count for a caller who cannot see every agent: the count includes
            the ones hidden from them. */}
        {ceiling.held === null
          ? t("bodyReached", { limit: ceiling.limit })
          : t("body", { limit: ceiling.limit, held: ceiling.held })}
      </AlertDescription>
    </Alert>
  );
}
