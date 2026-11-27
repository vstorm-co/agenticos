"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { RoutineAccessReview } from "@/lib/routine-access-api";
import { useOrgStore } from "@/stores";

type Fix = "connections" | "approvals" | null;

/**
 * The one reason worth reading first, of the several a review can carry: what
 * blocks saving, then why the routine is stopped, then what narrows the
 * choices. Null when there is nothing to say.
 */
function mostImportant(review: RoutineAccessReview): {
  key: string;
  values: Record<string, string>;
  fix: Fix;
  blocking: boolean;
} | null {
  if (review.required_unavailable_sources.length > 0)
    return {
      key: "banner.requiredUnavailable",
      values: { names: review.required_unavailable_sources.join(", ") },
      fix: "connections",
      blocking: true,
    };
  if (review.review_reason === "trust_not_allowed") {
    const reason = review.trust_blocked_reason ?? "other";
    return {
      key: "banner.trustNotAllowed",
      values: { reason },
      fix: reason === "organization" ? "approvals" : null,
      blocking: true,
    };
  }
  if (review.review_reason === "unavailable")
    return {
      key: "banner.unavailable",
      values: { names: review.unavailable_sources.join(", ") },
      fix: "connections",
      blocking: true,
    };
  if (review.review_reason !== null)
    return { key: `banner.${review.review_reason}`, values: {}, fix: null, blocking: true };
  if (review.allow_blocked_reason !== null)
    return {
      key: "banner.allowBlocked",
      values: { reason: review.allow_blocked_reason },
      fix: review.allow_blocked_reason === "organization" ? "approvals" : null,
      blocking: false,
    };
  return null;
}

export function RoutineAccessBanner({
  agentId,
  review,
}: {
  agentId: string;
  review: RoutineAccessReview;
}) {
  const t = useTranslations("triggers.access");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const reason = mostImportant(review);
  if (reason === null) return null;
  return (
    <Alert variant={reason.blocking ? "warning" : "info"}>
      <AlertDescription className="space-y-1 text-sm">
        <p>{t(reason.key, reason.values)}</p>
        {reason.fix === "connections" && (
          <Link
            className="underline underline-offset-4"
            href={`${ROUTES.AGENT_DETAIL(agentId)}?highlight=agent-mcp`}
          >
            {t("inspectAgent")}
          </Link>
        )}
        {/* The organization's setting is changed by whoever may decide approvals. */}
        {reason.fix === "approvals" && activeOrgId && (
          <Link
            className="underline underline-offset-4"
            href={`/orgs/${activeOrgId}/members?tab=governance`}
          >
            {t("openApprovalSettings")}
          </Link>
        )}
      </AlertDescription>
    </Alert>
  );
}
