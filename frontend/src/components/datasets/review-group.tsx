"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { ScoreGroup } from "@/lib/scoring";
import { formatDateTime } from "@/lib/utils";

interface ReviewGroupHeadingProps {
  group: ScoreGroup;
  /** Takes the group's waiting scores out of the queue; absent when there is nothing to take. */
  onWithdraw?: () => void;
  /** Scores these of the group's answers again; absent for somebody who may not. */
  onRescore?: (scoreIds: string[]) => void;
  busy: boolean;
  /** Link the eval run, which only a reader with `runs:view` may open. */
  linksRuns?: boolean;
}

/**
 * Where a group of scores came from - one eval run, or grading by hand - and what
 * to do with it: score its ungraded answers again, when there is more than one,
 * or take its waiting scores out of the queue.
 */
export function ReviewGroupHeading({
  group,
  onWithdraw,
  onRescore,
  busy,
  linksRuns = false,
}: ReviewGroupHeadingProps) {
  const t = useTranslations("datasets.scoring");
  const locale = useLocale();
  const [first] = group.scores;
  const when = formatDateTime(first!.created_at, locale);
  const ungraded = group.scores.filter((score) => score.unscored_reason !== null);
  const link =
    linksRuns && group.evalRunId !== null && first!.agent_id !== null
      ? `${ROUTES.AGENTS}/${first!.agent_id}/evals/${group.evalRunId}`
      : null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <h3 className="text-muted-foreground font-mono text-xs font-medium tracking-[0.1em] uppercase">
        {group.evalRunId === null ? t("groupByHand") : t("groupEvalRun", { when })}
        {" · "}
        {first!.agent_name ?? t("agentGone")}
      </h3>
      {link !== null && (
        <Link href={link} className="text-muted-foreground text-xs underline">
          {t("evalRunLink")}
        </Link>
      )}
      {onRescore && ungraded.length > 1 && (
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto h-7"
          disabled={busy}
          onClick={() => onRescore(ungraded.map((score) => score.id))}
        >
          {t("rescoreGroup", { count: ungraded.length })}
        </Button>
      )}
      {onWithdraw && (
        <Button
          variant="ghost"
          size="sm"
          className={onRescore && ungraded.length > 1 ? "h-7" : "ml-auto h-7"}
          disabled={busy}
          onClick={onWithdraw}
        >
          {t("withdrawGroup", {
            count: group.scores.filter((score) => score.human_passed === null).length,
          })}
        </Button>
      )}
    </div>
  );
}
