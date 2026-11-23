"use client";

import { AlertTriangle, Hourglass } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import type { RoutineBlocker, RoutineBlockerCode } from "@/lib/routine-readiness-api";
import { cn } from "@/lib/utils";

/** Fixed in the routine's own access review, which only its creator may open. */
const REVIEWED = new Set<RoutineBlockerCode>([
  "sources_setup",
  "sources_review",
  "platform_identity",
  "actions_need_approval",
]);
const PARKED = new Set<RoutineBlockerCode>(["awaiting_approval", "awaiting_answer"]);

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
  onReview: () => void;
  onOpenRuns: () => void;
}) {
  const t = useTranslations("triggers.blockers");
  if (blockers.length === 0) return null;
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
              blocked ? "text-destructive" : "text-warning-ink",
            )}
          >
            <Icon aria-hidden className="size-3.5 shrink-0" />
            <span className="min-w-0 flex-1">
              {t(blocker.code, { count: blocker.count ?? 0, held: blocked ? "yes" : "no" })}
            </span>
            {REVIEWED.has(blocker.code) &&
              (canReview ? (
                <Button variant="outline" size="sm" className="h-7" onClick={onReview}>
                  {t("review")}
                </Button>
              ) : (
                <span className="text-muted-foreground">{t("ownerOnly")}</span>
              ))}
            {PARKED.has(blocker.code) && (
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
