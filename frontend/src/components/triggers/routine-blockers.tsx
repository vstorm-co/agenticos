"use client";

import { AlertTriangle, Hourglass } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import {
  PARKED_CODES,
  type RoutineBlocker,
  type RoutineBlockerCode,
} from "@/lib/routine-readiness-api";
import { cn } from "@/lib/utils";
import { useRetryRoutineReadiness } from "@/hooks/use-routine-readiness";
import type { RoutineAccessTab } from "@/components/triggers/routine-access-dialog";

/**
 * Fixed in the routine's own access review, which only its creator may open,
 * and the tab of it each one concerns.
 */
const REVIEWED: Partial<Record<RoutineBlockerCode, RoutineAccessTab>> = {
  sources_setup: "tools",
  sources_review: "sources",
  routine_changed: "sources",
  platform_identity: "sources",
  trust_not_allowed: "tools",
  actions_need_approval: "tools",
};

/**
 * Why the next activation will not run, or will stop on a person - one line each,
 * with the way to fix it where this caller has one.
 */
export function RoutineBlockers({
  blockers,
  paused,
  canReview,
  onReview,
  onOpenRuns,
}: {
  blockers: RoutineBlocker[];
  /** A paused routine is not about to run: its lines say what resuming would meet. */
  paused: boolean;
  /** Whether the caller is the creator, who alone reviews sources and consent. */
  canReview: boolean;
  /** Open the access review on the tab the blocker concerns. */
  onReview: (tab: RoutineAccessTab) => void;
  onOpenRuns: () => void;
}) {
  const t = useTranslations("triggers.blockers");
  const common = useTranslations("common");
  const retry = useRetryRoutineReadiness();
  if (blockers.length === 0) return null;
  // Every reviewed reason is fixed in the same dialog, so only the first offers it.
  const reviewAt = blockers.find((blocker) => REVIEWED[blocker.code] !== undefined)?.code;
  return (
    <ul className="basis-full space-y-1" aria-label={t("label")}>
      {paused && blockers.some((blocker) => blocker.severity === "blocked") && (
        <li className="text-muted-foreground text-xs">{t("resumeBlocked")}</li>
      )}
      {blockers.map((blocker) => {
        const blocked = blocker.severity === "blocked";
        const Icon = blocked ? AlertTriangle : Hourglass;
        return (
          <li
            key={blocker.code}
            className={cn(
              "flex flex-wrap items-center gap-x-2 gap-y-1 text-xs",
              blocked
                ? "text-destructive"
                : blocker.severity === "unknown"
                  ? "text-muted-foreground"
                  : "text-warning-ink",
            )}
          >
            <Icon aria-hidden className="size-3.5 shrink-0" />
            <span className="min-w-0 flex-1">
              {t(blocker.code, { count: blocker.count ?? 0, held: blocked ? "yes" : "no" })}
            </span>
            {blocker.code === "readiness_unavailable" && (
              <Button variant="outline" size="sm" className="h-7" onClick={() => void retry()}>
                {common("retry")}
              </Button>
            )}
            {blocker.code === reviewAt &&
              (canReview ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7"
                  onClick={() => onReview(REVIEWED[blocker.code] ?? "tools")}
                >
                  {t("review")}
                </Button>
              ) : (
                <span className="text-muted-foreground">{t("ownerOnly")}</span>
              ))}
            {PARKED_CODES.has(blocker.code) && (
              <Button variant="outline" size="sm" className="h-7" onClick={onOpenRuns}>
                {t("openRuns")}
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
