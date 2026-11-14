"use client";

import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/dashboard/page-header";
import { LoadingState } from "@/components/states";
import { Skeleton } from "@/components/ui";
import { ROUTES } from "@/lib/constants";

export const WORKFLOW_RUN_LAYOUT = "flex min-h-0 flex-1 flex-col gap-4";
export const WORKFLOW_RUN_PANELS =
  "grid min-h-[34rem] flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]";

/** Keep the run's metrics and graph/steps split in place before the graph is known. */
export function WorkflowRunLoading() {
  const t = useTranslations("pages.workflows");
  return (
    <div aria-busy="true" className={WORKFLOW_RUN_LAYOUT}>
      <PageHeader
        title={<Skeleton className="h-8 w-64 max-w-full" />}
        breadcrumbs={[{ label: t("title"), href: ROUTES.WORKFLOWS }, { label: "…" }]}
        badges={<Skeleton className="h-5 w-32 rounded-full" />}
        actions={<Skeleton aria-hidden className="h-9 w-32 rounded-lg" />}
      />
      <dl className="bg-card grid shrink-0 grid-cols-3 divide-x overflow-hidden rounded-xl border">
        {[t("runDuration"), t("runCost"), t("runSteps")].map((label) => (
          <div key={label} className="min-w-0 px-3 py-3 sm:px-5 sm:py-4">
            <dt className="text-muted-foreground text-xs">{label}</dt>
            <dd className="mt-1">
              <Skeleton aria-hidden className="h-6 w-20" />
            </dd>
          </div>
        ))}
      </dl>
      <div className={WORKFLOW_RUN_PANELS}>
        <div className="border-border bg-card min-h-[28rem] overflow-hidden rounded-xl border lg:min-h-0">
          <LoadingState variant="pending" className="h-full min-h-[28rem]" />
        </div>
        <div aria-hidden="true" className="border-border bg-card space-y-4 rounded-xl border p-4">
          <Skeleton className="h-5 w-28" />
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-12 w-full rounded-lg" />
          ))}
        </div>
      </div>
    </div>
  );
}
