"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { Badge, Button, ListCard, Pager, Skeleton } from "@/components/ui";
import { useSkillCheckHistory } from "@/hooks/use-skill-check";
import { useUrlOverlay } from "@/hooks/use-url-state";
import { getErrorMessage } from "@/lib/api-error";
import { CHECK_PAGE_SIZE } from "@/lib/skill-checks-api";
import { formatDateTime } from "@/lib/utils";
import type { CheckStatus, SkillCheck } from "@/types/skill-checks";
import { SkillCheckDialog, type CheckedDraft } from "./skill-check-dialog";

const TONE: Record<CheckStatus, "default" | "secondary" | "outline" | "destructive"> = {
  running: "outline",
  done: "default",
  cancelled: "secondary",
  applied: "secondary",
  forked: "secondary",
  discarded: "secondary",
};

/**
 * The checks of changes to one line of a skill, newest first and a page at a time:
 * when each ran, the version it was written over, what it found and what was done
 * with it. Details opens the check as it was decided, or to decide it for a reader
 * who may; `?check=` opens one by id, which is how a stage's run page leads back to
 * its check.
 */
export function SkillChecks({
  skillId,
  forkId,
  canDecide,
  onEdit,
}: {
  skillId: string;
  forkId: string | null;
  /** Whether the reader may decide a check, or only read what each one found. */
  canDecide: boolean;
  onEdit: (draft: CheckedDraft) => void;
}) {
  const t = useTranslations("skills.page.checks");
  const tErrors = useTranslations("errors");
  const [page, setPage] = useState(0);
  const { checks, total, isLoading, error } = useSkillCheckHistory(skillId, forkId, page);
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
      {total > CHECK_PAGE_SIZE && (
        <Pager
          page={page}
          pageCount={Math.ceil(total / CHECK_PAGE_SIZE)}
          matched={total}
          total={total}
          onPage={setPage}
          counted={t("count", { count: total })}
        />
      )}
      {opened !== null && (
        <SkillCheckDialog
          skillId={skillId}
          resume={opened}
          forkId={forkId}
          canDecide={canDecide}
          onOpenChange={(open) => !open && overlay.close()}
          onEdit={(draft) => {
            // Going back over the overlay's history entry would undo the line the editor opens on.
            overlay.replace(null);
            onEdit(draft);
          }}
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
