"use client";

import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { RunHistory } from "@/components/workflows/runs/run-history";
import { ROUTES } from "@/lib/constants";

/**
 * Every workflow's runs the caller may see, newest first: one place to find
 * what failed overnight across all of them, filtered by state, version and what
 * started each run. A row opens the run on its own workflow's page.
 */
export default function AllWorkflowRunsPage() {
  const t = useTranslations("pages.workflows");
  return (
    <div className="space-y-6">
      <PageHeader
        title={t("allRunsTitle")}
        description={t("allRunsDescription")}
        breadcrumbs={[{ label: t("title"), href: ROUTES.WORKFLOWS }, { label: t("allRunsTitle") }]}
      />
      <RunHistory />
    </div>
  );
}
