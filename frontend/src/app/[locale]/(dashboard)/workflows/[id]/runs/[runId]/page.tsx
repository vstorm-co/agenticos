"use client";

import { use } from "react";
import { Activity } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { ListCard, ListCardEmpty } from "@/components/ui";
import { useWorkflow } from "@/hooks";
import { ROUTES } from "@/lib/constants";

interface PageProps {
  params: Promise<{ id: string; runId: string }>;
}

/**
 * One test/production run: per-step inputs, outputs and costs on a read-only
 * canvas. Designed here, buildable once #1788's `WorkflowRun`/`NodeRun` and its
 * event stream exist — the foundation is a typed shell with the unavailable state.
 */
export default function WorkflowRunDetailPage({ params }: PageProps) {
  const { id, runId } = use(params);
  const t = useTranslations("pages.workflows");
  const { workflow } = useWorkflow(id);

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("runTitle")}
        breadcrumbs={[
          { label: t("title"), href: ROUTES.WORKFLOWS },
          { label: workflow?.name ?? t("runTitle"), href: ROUTES.WORKFLOW_DETAIL(id) },
          { label: t("runsTitle"), href: ROUTES.WORKFLOW_RUNS(id) },
          { label: runId },
        ]}
      />
      <ListCard title={t("runTitle")} counted={null}>
        <ListCardEmpty icon={Activity} title={t("runUnavailable")} />
      </ListCard>
    </div>
  );
}
