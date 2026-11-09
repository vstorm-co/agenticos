"use client";

import { useLocale, useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { Badge, Button, ListCard, Skeleton } from "@/components/ui";
import { useSkillCheckHistory } from "@/hooks/use-skill-check";
import { useUrlOverlay } from "@/hooks/use-url-state";
import { getErrorMessage } from "@/lib/api-error";
import { formatDateTime } from "@/lib/utils";
import type { CheckStatus, SkillCheck } from "@/types/skill-checks";
import { SkillCheckDialog } from "./skill-check-dialog";

const TONE: Record<CheckStatus, "default" | "secondary" | "outline" | "destructive"> = {
  running: "outline",
  done: "default",
  cancelled: "secondary",
  applied: "secondary",
  forked: "secondary",
  discarded: "secondary",
};

/**
 * The checks of changes to one line of a skill, newest first: when each ran, the
 * version it was written over, what it found and what was done with it. Details
 * opens the check as it was decided, or to decide it; `?check=` opens one by id,
 * which is how a stage's run page leads back to its check.
 */
export function SkillChecks({
  skillId,
  forkId,
  onEdit,
}: {
  skillId: string;
  forkId: string | null;
  onEdit: (candidate: { description: string; content: string }) => void;
}) {
  const t = useTranslations("skills.page.checks");
  const tErrors = useTranslations("errors");
  const { checks, total, isLoading, error } = useSkillCheckHistory(skillId, forkId);
  const [opened, overlay] = useUrlOverlay("check");
  return (
    <ListCard title={t("title")} counted={checks ? t("count", { count: total }) : null}>
      {error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} />
      ) : isLoading || !checks ? (
        <Skeleton className="m-4 h-16" />
      ) : checks.length === 0 ? (
        <p className="text-muted-foreground p-4 text-sm">{t("none")}</p>
      ) : (
        <ul className="divide-border divide-y">
          {checks.map((check) => (
            <CheckRow key={check.id} check={check} onOpen={() => overlay.open(check.id)} />
          ))}
        </ul>
      )}
      {opened !== null && (
        <SkillCheckDialog
          skillId={skillId}
          resume={opened}
          forkId={forkId}
          onOpenChange={(open) => !open && overlay.close()}
          onEdit={onEdit}
        />
      )}
    </ListCard>
  );
}

function CheckRow({ check, onOpen }: { check: SkillCheck; onOpen: () => void }) {
  const t = useTranslations("skills.page.checks");
  const locale = useLocale();
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
      <div className="min-w-0 space-y-0.5">
        <p className="font-medium">
          {t("over", {
            version: check.base_version.number,
            agents: check.agents.length + check.hidden,
          })}
        </p>
        <p className="text-muted-foreground text-xs">
          {formatDateTime(check.created_at, locale)}
          {check.verdict !== null && ` · ${t(`verdict.${check.verdict}`)}`}
        </p>
      </div>
      <span className="flex items-center gap-2">
        <Badge variant={TONE[check.status]}>{t(`status.${check.status}`)}</Badge>
        <Button variant="outline" size="sm" onClick={onOpen}>
          {t("details")}
        </Button>
      </span>
    </li>
  );
}
