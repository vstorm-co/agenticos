"use client";

import { useState } from "react";
import Link from "next/link";
import { FlaskConical, Play } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useDatasets } from "@/hooks/use-datasets";
import { useEvalRuns } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { EvalRun } from "@/types/eval-runs";
import { EvalStatusBadge } from "./eval-status-badge";
import { percent, usd } from "./format";
import { StartEvalDialog } from "./start-eval-dialog";

interface EvalsPanelProps {
  agentId: string;
  /** Whether the caller may start one: run the agent, and run a dataset. */
  canStart: boolean;
  /** Whether the caller may run the draft, which is the editors' work in progress. */
  canRunDraft: boolean;
  /** The published version, or null for an agent nobody published. */
  currentVersion: number | null;
}

/** The candidate a run measured, as a short label: "v7", "Draft" or "Proposed". */
export function candidateLabel(
  run: EvalRun,
  t: (key: string, values?: { version: number }) => string,
) {
  const candidate = run.arms.find((arm) => arm.role === "candidate");
  if (!candidate || candidate.version_number === null) {
    return candidate?.source === "explicit" ? t("proposed") : t("draft");
  }
  return t("version", { version: candidate.version_number });
}

function RunRow({ agentId, run }: { agentId: string; run: EvalRun }) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const candidates = run.arms.filter((arm) => arm.role === "candidate");
  return (
    <li>
      <Link
        href={`${ROUTES.AGENTS}/${agentId}/evals/${run.id}`}
        className="hover:bg-accent/40 flex flex-wrap items-center justify-between gap-3 rounded-md px-2 py-3"
      >
        <span className="min-w-0 space-y-1">
          <span className="text-foreground block truncate text-sm font-medium">
            {t("runTitle", {
              dataset: run.dataset_name,
              version: run.dataset_version,
              candidate: candidateLabel(run, t),
            })}
          </span>
          <span className="text-muted-foreground block text-xs">
            {formatDateTime(run.created_at, locale)} ·{" "}
            {candidates.map((arm) => arm.model_label).join(", ")}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-3 text-xs">
          {candidates.map((arm) => (
            <span key={arm.id} className="text-foreground tabular-nums">
              {percent(arm.summary.pass_rate, locale)}
            </span>
          ))}
          <span className="text-muted-foreground tabular-nums">{usd(run.cost_usd, locale)}</span>
          <EvalStatusBadge status={run.status} />
        </span>
      </Link>
    </li>
  );
}

/**
 * The Evals tab: every run of this agent over a dataset, newest first, and
 * where a new one starts. A run is rare and costs money, so starting one is a
 * button here rather than a control on every screen.
 */
export function EvalsPanel({ agentId, canStart, canRunDraft, currentVersion }: EvalsPanelProps) {
  const t = useTranslations("evals");
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");
  const [starting, setStarting] = useState(false);
  const { runs, isLoading, error, refetch } = useEvalRuns(agentId);
  const { datasets } = useDatasets({ sort: "updated", limit: 1 });
  const startable = canStart && (currentVersion !== null || canRunDraft);
  const start = startable ? { label: t("start"), onClick: () => setStarting(true) } : undefined;

  return (
    <Card data-tour="agent-evals">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1.5">
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </div>
        {start && runs.length > 0 && (
          <Button size="sm" onClick={start.onClick}>
            <Play className="h-3.5 w-3.5" aria-hidden />
            {start.label}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <LoadingState variant="skeleton-list" rows={3} />
        ) : error ? (
          <ErrorState
            description={getErrorMessage(error, tErrors)}
            cta={{ label: tc("retry"), onClick: () => void refetch() }}
          />
        ) : runs.length === 0 ? (
          datasets.length === 0 ? (
            <EmptyState
              icon={FlaskConical}
              title={t("empty.noDatasetTitle")}
              description={t("empty.noDatasetBody")}
              cta={{ label: t("empty.createDataset"), href: ROUTES.DATASETS }}
            />
          ) : (
            <EmptyState
              icon={FlaskConical}
              title={t("empty.title")}
              description={t("empty.body")}
              cta={start}
            />
          )
        ) : (
          <ul className="divide-border divide-y">
            {runs.map((run) => (
              <RunRow key={run.id} agentId={agentId} run={run} />
            ))}
          </ul>
        )}
      </CardContent>
      {starting && (
        <StartEvalDialog
          agentId={agentId}
          canRunDraft={canRunDraft}
          currentVersion={currentVersion}
          onOpenChange={setStarting}
        />
      )}
    </Card>
  );
}
