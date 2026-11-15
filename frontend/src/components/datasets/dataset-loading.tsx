"use client";

import { ClipboardCheck, ListChecks, Settings2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/dashboard/page-header";
import { ListCard, Skeleton, Tabs, TabsList, TabsTrigger } from "@/components/ui";
import { ROUTES } from "@/lib/constants";

/** Keep the dataset header, workspace tabs and full-height cases surface while metadata loads. */
export function DatasetLoading() {
  const t = useTranslations("datasets");
  const states = useTranslations("states");
  return (
    <div
      className="flex flex-1 flex-col gap-4"
      role="status"
      aria-busy="true"
      aria-label={states("loading")}
    >
      <div inert aria-hidden="true" className="flex flex-1 flex-col gap-4">
        <PageHeader
          title={<Skeleton className="h-7 w-56 max-w-full" />}
          breadcrumbs={[{ label: t("title"), href: ROUTES.DATASETS }, { label: states("loading") }]}
          actions={<Skeleton className="size-9 rounded-lg" />}
        />
        <Tabs value="cases" className="flex flex-1 flex-col gap-4">
          <TabsList>
            <TabsTrigger disabled value="cases">
              <ListChecks className="size-4" />
              {t("cases")}
            </TabsTrigger>
            <TabsTrigger disabled value="results">
              <ClipboardCheck className="size-4" />
              {t("workspace.results")}
            </TabsTrigger>
            <TabsTrigger disabled value="settings">
              <Settings2 className="size-4" />
              {t("settingsTab")}
            </TabsTrigger>
          </TabsList>
          <ListCard fill namedByPage title={t("cases")} counted={null}>
            <div className="flex min-h-72 flex-1 items-center justify-center">
              <Skeleton className="size-6 rounded-full" />
            </div>
          </ListCard>
        </Tabs>
      </div>
    </div>
  );
}
