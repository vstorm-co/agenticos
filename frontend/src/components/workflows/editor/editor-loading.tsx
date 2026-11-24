"use client";

import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { LoadingState } from "@/components/states";
import { Skeleton } from "@/components/ui";
import { ROUTES } from "@/lib/constants";

export const WORKFLOW_EDITOR_LAYOUT = "flex min-h-0 flex-1 flex-col gap-3 pb-4 sm:min-h-[40rem]";
export const WORKFLOW_EDITOR_CANVAS =
  "border-border bg-card relative flex min-h-0 flex-1 overflow-hidden rounded-xl border";

/** Reserve the editor shell without inventing a graph before its catalog arrives. */
export function WorkflowEditorLoading() {
  const t = useTranslations("pages.workflows");

  return (
    <div className={WORKFLOW_EDITOR_LAYOUT}>
      <PageHeader
        className="mb-0 md:mb-0"
        title={<Skeleton className="h-6 w-40 max-w-full sm:h-8 sm:w-64" />}
        icon={<Skeleton className="size-10 shrink-0 rounded-xl" />}
        breadcrumbs={[{ label: t("title"), href: ROUTES.WORKFLOWS }, { label: "…" }]}
        badges={<Skeleton className="h-6 w-28 rounded-full" />}
        actions={
          <div aria-hidden="true" className="flex flex-wrap items-center gap-2">
            <Skeleton className="touch:min-h-11 size-9 rounded-lg" />
            <Skeleton className="touch:min-h-11 h-9 w-20 rounded-lg" />
            <Skeleton className="touch:min-h-11 h-9 w-24 rounded-lg" />
          </div>
        }
      />
      <div data-workflow-editor className={WORKFLOW_EDITOR_CANVAS}>
        <LoadingState variant="pending" className="min-h-[28rem] w-full flex-1" />
      </div>
    </div>
  );
}
