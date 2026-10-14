"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Square } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  Card,
  CardContent,
  Progress,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { isLive, useEvalComparison, useEvalRun } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { EvalRun } from "@/types/eval-runs";
import { ArmsTable } from "./arms-table";
import { CaseTable } from "./case-table";
import { ComparisonCard } from "./comparison-card";
import { EvalStatusBadge } from "./eval-status-badge";
import { candidateLabel } from "./evals-panel";
import { usd } from "./format";

function RunHeader({ run, onCancel }: { run: EvalRun; onCancel?: () => void }) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const done = run.attempts_total === 0 ? 0 : (run.attempts_done / run.attempts_total) * 100;
  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <h1 className="text-lg font-semibold">
              {t("runTitle", {
                dataset: run.dataset_name,
                version: run.dataset_version,
                candidate: candidateLabel(run, t),
              })}
            </h1>
            <p className="text-muted-foreground text-xs">
              {t("runMeta", {
                date: formatDateTime(run.created_at, locale),
                cost: usd(run.cost_usd, locale),
                estimate: usd(run.estimate_usd, locale),
              })}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <EvalStatusBadge status={run.status} />
            {onCancel && (
              <Button size="sm" variant="outline" onClick={onCancel}>
                <Square className="h-3.5 w-3.5" aria-hidden />
                {t("cancelRun")}
              </Button>
            )}
          </div>
        </div>
        <Progress value={done} aria-label={t("progress")} />
        <p className="text-muted-foreground text-xs">
          {t("progressCount", { done: run.attempts_done, total: run.attempts_total })}
        </p>
        {run.error && <p className="text-destructive text-sm">{run.error}</p>}
      </CardContent>
    </Card>
  );
}

/** One eval run: where it is, how each arm did, how it compares, and every case. */
export function EvalRunView({ agentId, runId }: { agentId: string; runId: string }) {
  const t = useTranslations("evals");
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");
  const { run, isLoading, error, refetch, cancel } = useEvalRun(runId);
  const candidates = run?.arms.filter((arm) => arm.role === "candidate") ?? [];
  const [arm, setArm] = useState<string | null>(null);
  const focus = arm ?? candidates[0]?.id ?? null;
  const live = run !== undefined && isLive(run.status);
  const { comparison, refetch: refetchComparison } = useEvalComparison(runId, {
    arm: focus,
    live,
  });
  // The run and its verdict are polled apart, so the poll that sees the run end
  // can stop the verdict's before it read the last reruns: read it once more.
  const wasLive = useRef(live);
  useEffect(() => {
    if (wasLive.current && !live) void refetchComparison();
    wasLive.current = live;
  }, [live, refetchComparison]);

  if (isLoading) return <LoadingState variant="skeleton-cards" rows={3} />;
  if (error || !run) {
    return (
      <ErrorState
        description={getErrorMessage(error, tErrors)}
        cta={{ label: tc("retry"), onClick: () => void refetch() }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <Link
        href={`${ROUTES.AGENTS}/${agentId}?tab=evals`}
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        {t("back")}
      </Link>
      <RunHeader
        run={run}
        onCancel={
          isLive(run.status)
            ? () =>
                cancel.mutate(undefined, {
                  onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
                })
            : undefined
        }
      />
      <ArmsTable arms={run.arms} />
      {candidates.length > 1 && (
        <Select value={focus ?? ""} onValueChange={setArm}>
          <SelectTrigger aria-label={t("compareArm")} className="w-64">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {candidates.map((candidate) => (
              <SelectItem key={candidate.id} value={candidate.id}>
                {candidate.model_label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {comparison && <ComparisonCard agentId={agentId} comparison={comparison} />}
      <CaseTable run={run} flips={comparison?.cases ?? []} />
    </div>
  );
}
