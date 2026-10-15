"use client";

import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { ScoreGroup } from "@/lib/scoring";

interface ReviewGroupHeadingProps {
  group: ScoreGroup;
  /** Takes the group's waiting scores out of the queue; absent when there is nothing to take. */
  onWithdraw?: () => void;
  busy: boolean;
}

/** Where a group of scores came from - one eval run, or grading by hand - and what to do with it. */
export function ReviewGroupHeading({ group, onWithdraw, busy }: ReviewGroupHeadingProps) {
  const t = useTranslations("datasets.scoring");
  const format = useFormatter();
  const [first] = group.scores;
  const when = format.dateTime(new Date(first!.created_at), {
    dateStyle: "medium",
    timeStyle: "short",
  });
  const link =
    group.evalRunId !== null && first!.agent_id !== null
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
      {onWithdraw && (
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto h-7"
          disabled={busy}
          onClick={onWithdraw}
        >
          {t("withdrawGroup", { count: group.scores.length })}
        </Button>
      )}
    </div>
  );
}
