"use client";

import { use } from "react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { WorkflowLogs } from "@/components/workflows/logs/workflow-logs";
import { useWorkflow } from "@/hooks";
import { ROUTES } from "@/lib/constants";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * A workflow's log: what its steps' quick logs wrote across runs, newest first,
 * filtered on the server. Laid out like the runs page beside it; a line opens the
 * run that wrote it.
 */
export default function WorkflowLogsPage({ params }: PageProps) {
  const { id } = use(params);
  const t = useTranslations("pages.workflows");
  const { workflow } = useWorkflow(id);

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("logsTitle")}
        description={t("logsDescription")}
        breadcrumbs={[
          { label: t("title"), href: ROUTES.WORKFLOWS },
          { label: workflow?.name ?? t("logsTitle"), href: ROUTES.WORKFLOW_DETAIL(id) },
          { label: t("logsTitle") },
        ]}
      />
      <WorkflowLogs workflowId={id} />
    </div>
  );
}
