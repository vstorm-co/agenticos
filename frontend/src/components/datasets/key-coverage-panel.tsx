"use client";

import { useId, useState } from "react";
import { Loader2, SearchCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Label, ListCard, NativeSelect } from "@/components/ui";
import { useEveryAgent } from "@/hooks/use-eval-runs";
import { useKeyCoverage } from "@/hooks/use-key-coverage";
import { getErrorMessage } from "@/lib/api-error";
import type { Agent } from "@/types/agents";
import type { CoverageItem, KeyCoverageReport } from "@/types/datasets";

const ORDER: CoverageItem["verdict"][] = ["not_covered", "unsure", "covered"];

/**
 * Which of the dataset's keys none of an agent's sources holds.
 *
 * Any published agent the reader may see can be chosen; asking for a new report
 * is offered to who may edit it. Uncovered keys come first: they are the facts a
 * person must give the agent, since no change to its instructions can.
 */
export function KeyCoveragePanel({ datasetId }: { datasetId: string }) {
  const t = useTranslations("datasets.keyCoverage");
  const tErrors = useTranslations("errors");
  const pickerId = useId();
  const { agents, isLoading, error } = useEveryAgent();
  const published = agents.filter(
    (agent) => (agent.kind ?? "agent") === "agent" && agent.current_version_id !== null,
  );
  const [chosen, setChosen] = useState<string | null>(null);
  const agent = published.find((item) => item.id === chosen) ?? null;

  if (isLoading) return <LoadingState variant="pending" />;
  if (error) return <ErrorState description={getErrorMessage(error, tErrors, t("agentsFailed"))} />;
  if (published.length === 0) {
    return <EmptyState icon={SearchCheck} title={t("noAgents")} description={t("noAgentsHint")} />;
  }
  return (
    <ListCard title={t("title")}>
      <div className="space-y-4 p-4">
        <p className="text-muted-foreground text-sm">{t("hint")}</p>
        <div className="max-w-sm space-y-1.5">
          <Label htmlFor={pickerId}>{t("agent")}</Label>
          <NativeSelect
            id={pickerId}
            value={chosen ?? ""}
            onChange={(event) => setChosen(event.target.value || null)}
          >
            <option value="">{t("chooseAgent")}</option>
            {published.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        {agent && <AgentCoverage key={agent.id} datasetId={datasetId} agent={agent} />}
      </div>
    </ListCard>
  );
}

function AgentCoverage({ datasetId, agent }: { datasetId: string; agent: Agent }) {
  const t = useTranslations("datasets.keyCoverage");
  const { report, loading, error, start, starting } = useKeyCoverage(datasetId, agent.id);
  const running = report?.status === "running";

  if (loading) return <LoadingState variant="pending" />;
  if (error) {
    return (
      <p className="text-destructive text-sm" role="alert">
        {t("unreadable")}
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {agent.can_edit && (
        <Button size="sm" onClick={start} disabled={starting || running}>
          {starting || running ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <SearchCheck className="size-4" aria-hidden />
          )}
          {report ? t("recheck") : t("check")}
        </Button>
      )}
      {report === null ? (
        <p className="text-muted-foreground text-sm">
          {agent.can_edit ? t("none") : t("noneReadOnly")}
        </p>
      ) : (
        <Report report={report} />
      )}
    </div>
  );
}

function Report({ report }: { report: KeyCoverageReport }) {
  const t = useTranslations("datasets.keyCoverage");
  if (report.status === "running") {
    return (
      <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {t("running")}
      </p>
    );
  }
  if (report.status === "failed") {
    return (
      <p className="text-destructive text-sm" role="alert">
        {t("failed", { error: report.error ?? "" })}
      </p>
    );
  }
  const items = [...report.items].sort(
    (a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict),
  );
  const counted = (verdict: CoverageItem["verdict"]) =>
    items.filter((item) => item.verdict === verdict).length;
  return (
    <div className="space-y-3">
      <p className="text-sm" role="status">
        {t("summary", {
          count: items.length,
          version: report.dataset_version,
          covered: counted("covered"),
          uncovered: counted("not_covered"),
          unsure: counted("unsure"),
        })}
      </p>
      {!report.current && (
        <p className="text-muted-foreground text-sm">
          {t(report.sources_changed ? "sourcesChanged" : "outOfDate")}
        </p>
      )}
      {report.unseen_sources > 0 && (
        <p className="text-muted-foreground text-sm">
          {t("unseen", { count: report.unseen_sources })}
        </p>
      )}
      <ul className="divide-y rounded-lg border text-sm">
        {items.map((item) => (
          <li key={item.key} className="space-y-1 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium break-words">{item.key}</span>
              <span
                className={
                  item.verdict === "not_covered"
                    ? "text-destructive"
                    : item.verdict === "unsure"
                      ? "text-muted-foreground"
                      : "text-emerald-700 dark:text-emerald-400"
                }
              >
                {t(`verdict.${item.verdict}`)}
              </span>
            </div>
            {item.sources.length > 0 && (
              <p className="text-muted-foreground">
                {t("from", {
                  sources: item.sources
                    .map((source) => source.name ?? t("hiddenSource"))
                    .join(", "),
                })}
              </p>
            )}
            {item.why && <p className="text-muted-foreground break-words">{item.why}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
