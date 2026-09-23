"use client";

import { use } from "react";
import { Activity } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { ListCard, ListCardEmpty } from "@/components/ui";
import { useWorkflow } from "@/hooks";
import { ROUTES } from "@/lib/constants";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * A workflow's run history. Designed here, buildable once #1788 (durable run
 * state) lands — the foundation is a typed shell with the unavailable state.
 */
export default function WorkflowRunsPage({ params }: PageProps) {
  const { id } = use(params);
  const t = useTranslations("pages.workflows");
  const { workflow } = useWorkflow(id);

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("runsTitle")}
        description={t("runsDescription")}
        breadcrumbs={[
          { label: t("title"), href: ROUTES.WORKFLOWS },
          { label: workflow?.name ?? t("runsTitle"), href: ROUTES.WORKFLOW_DETAIL(id) },
          { label: t("runsTitle") },
        ]}
      />
      <ListCard title={t("runsTitle")} counted={null}>
        <ListCardEmpty
          icon={Activity}
          title={t("runsUnavailable")}
          description={t("runsUnavailableDetail")}
        />
      </ListCard>
    </div>
  );
}
