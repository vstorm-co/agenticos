"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FlaskConical, Lock } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { EvalRunRow } from "@/components/evals/run-row";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { ListCard, ListCardEmpty, Pager } from "@/components/ui";
import { useAgents, usePermissions } from "@/hooks";
import { useRecentEvalRuns } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

/** A page of runs: the API reads at most fifty at once. */
const PAGE = 20;

/**
 * Every eval run the reader may see, across agents, newest first - where the
 * dashboard's Eval runs card goes on "See all". Each row opens the run; an agent's
 * Evals tab and a dataset's hold the same runs narrowed to one of them.
 */
export default function EvalRunsPage() {
  const t = useTranslations("evals.all");
  const tEvals = useTranslations("evals");
  const tNav = useTranslations("nav");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const { can, isLoading: isLoadingPermissions } = usePermissions();
  const [page, setPage] = useState(0);
  const mayRead = can(Perm.runsView);
  const { runs, total, isLoading, error, refetch } = useRecentEvalRuns(PAGE, {
    skip: page * PAGE,
    enabled: mayRead,
  });
  // Names need agents:view; without it a row starts at what was tested.
  const { agents } = useAgents({ enabled: can(Perm.agentsView) });
  const names = new Map(agents.map((agent) => [agent.id, agent.name]));

  const header = (
    <PageHeader
      title={t("title")}
      description={t("description")}
      breadcrumbs={[{ label: tNav("dashboard"), href: ROUTES.DASHBOARD }, { label: t("title") }]}
    />
  );

  if (!isLoadingPermissions && !mayRead) {
    return (
      <div className="space-y-6">
        {header}
        <EmptyState icon={Lock} title={t("noAccess")} description={t("noAccessBody")} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {header}
      <ListCard
        headerTour="evals-all"
        title={t("title")}
        counted={error || isLoading ? null : tEvals("runCount", { count: total })}
      >
        {isLoading || isLoadingPermissions ? (
          <LoadingState variant="skeleton-list" rows={4} />
        ) : error ? (
          <ErrorState
            description={getErrorMessage(error, tErrors)}
            cta={{ label: tc("retry"), onClick: () => void refetch() }}
          />
        ) : total === 0 ? (
          <ListCardEmpty
            icon={FlaskConical}
            title={t("empty.title")}
            description={t("empty.body")}
            cta={{ label: t("empty.cta"), onClick: () => router.push(ROUTES.DATASETS) }}
          />
        ) : (
          <div className="space-y-4">
            <ul className="divide-border divide-y">
              {runs.map((run) => (
                <EvalRunRow key={run.id} run={run} agentName={names.get(run.agent_id)} />
              ))}
            </ul>
            <Pager
              page={page}
              pageCount={Math.max(1, Math.ceil(total / PAGE))}
              matched={total}
              total={total}
              onPage={setPage}
              counted={tEvals("runCount", { count: total })}
            />
          </div>
        )}
      </ListCard>
    </div>
  );
}
