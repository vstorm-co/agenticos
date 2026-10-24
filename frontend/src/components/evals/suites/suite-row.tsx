"use client";

import { ReviewReevaluationNote } from "@/components/evals/review-reevaluation-note";
import { useState } from "react";
import { ListChecks, Pause, Pencil, Play, Trash2, Zap } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, Button, ConfirmDialog } from "@/components/ui";
import { useEvalSuites } from "@/hooks/use-eval-suites";
import { formatDateTime } from "@/lib/utils";
import type { EvalSuite } from "@/types/eval-suites";
import { percent } from "../format";
import { SuiteFormDialog } from "./suite-form-dialog";
import { RESULT_TONE, thresholdText, whenLabels } from "./suite-format";
import { SuitePinBadge } from "./suite-pin";
import { SuiteResultsSheet } from "./suite-results-sheet";

/**
 * One suite: what it holds the agent to, when it runs, and how it last came out -
 * opening its results in a drawer, as a routine opens its runs.
 *
 * The actions are the routine row's, for the same reason: running, editing,
 * pausing and removing are what a person does to a standing arrangement.
 */
export function SuiteRow({ suite, canManage }: { suite: EvalSuite; canManage: boolean }) {
  const t = useTranslations("evals.suites");
  const tDays = useTranslations("triggers");
  const locale = useLocale();
  const { setActive, runNow, remove } = useEvalSuites(suite.agent_id);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [viewing, setViewing] = useState(false);
  const last = suite.last_result;
  const running = suite.open_result?.status === "running";
  const when = whenLabels(suite, t, tDays);

  return (
    <div className="hover:border-foreground/20 flex flex-wrap items-center gap-3 rounded-xl border p-3 transition-colors sm:flex-nowrap">
      <button
        type="button"
        onClick={() => setViewing(true)}
        aria-label={t("viewResults", { name: suite.name })}
        className="hover:bg-muted/40 -m-1 flex min-w-0 flex-1 basis-full items-center gap-3 rounded-lg p-1 text-left transition-colors sm:basis-auto"
      >
        <span className="bg-muted flex h-10 w-10 shrink-0 items-center justify-center rounded-lg">
          <ListChecks className="text-muted-foreground h-5 w-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="truncate text-sm font-medium">{suite.name}</p>
          <p className="text-muted-foreground truncate text-xs">
            {t("holds", {
              dataset: suite.dataset_name ?? t("hiddenDataset"),
              environment: suite.environment_name ?? "none",
            })}
          </p>
          <p className="text-muted-foreground/80 truncate text-xs">
            {when.length > 0 ? when.join(" · ") : t("when.manualOnly")}
          </p>
        </div>
      </button>
      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        {running && <Badge variant="secondary">{t("status.running")}</Badge>}
        <SuitePinBadge suite={suite} />
        {last && (
          <Badge variant={RESULT_TONE[last.status]}>
            {last.summary?.pass_rate != null && last.status !== "skipped"
              ? t("lastResult", {
                  status: t(`status.${last.status}`),
                  rate: percent(last.summary.pass_rate, locale),
                })
              : t(`status.${last.status}`)}
          </Badge>
        )}
        <span className="text-muted-foreground text-xs" title={t("form.threshold")}>
          {thresholdText(suite.threshold, t, locale)}
        </span>
        {!suite.is_active && (
          <Badge variant="outline">
            {suite.paused_reason ? t(`paused.${suite.paused_reason}`) : t("paused.byPerson")}
          </Badge>
        )}
        {suite.is_active && suite.next_fire_at && (
          <span className="text-muted-foreground text-xs">
            {t("next", { date: formatDateTime(suite.next_fire_at, locale) })}
          </span>
        )}
      </div>
      {last?.summary?.review && <ReviewReevaluationNote review={last.summary.review} />}
      {canManage && (
        <div className="ml-auto flex shrink-0 items-center gap-0.5 sm:ml-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={t("runNow")}
            disabled={!suite.is_active || running || runNow.isPending}
            onClick={() => runNow.mutate(suite.id, { onSuccess: () => setViewing(true) })}
          >
            <Zap className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={t("edit")}
            onClick={() => setEditing(true)}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={suite.is_active ? t("pause") : t("resume")}
            disabled={setActive.isPending}
            onClick={() => setActive.mutate({ suiteId: suite.id, isActive: !suite.is_active })}
          >
            {suite.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="hover:text-destructive h-8 w-8"
            aria-label={t("delete")}
            disabled={remove.isPending}
            onClick={() => setDeleting(true)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      )}
      {editing && (
        <SuiteFormDialog agentId={suite.agent_id} suite={suite} onOpenChange={setEditing} />
      )}
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={t("deleteTitle")}
        description={t("deleteConfirm", { name: suite.name })}
        confirmLabel={t("delete")}
        destructive
        onConfirm={() => remove.mutate(suite.id)}
      />
      <SuiteResultsSheet suite={suite} open={viewing} onOpenChange={setViewing} />
    </div>
  );
}
