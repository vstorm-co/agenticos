"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, ListCard } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { diagnosticsStatusSchema } from "@/lib/diagnostics";
import { qk } from "@/lib/query-keys";

export function DiagnosticsCard() {
  const t = useTranslations("pages.adminDiagnostics");
  const query = useQuery({
    queryKey: qk.admin.diagnostics(),
    queryFn: async ({ signal }) =>
      diagnosticsStatusSchema.parse(await apiClient.get<unknown>("/admin/diagnostics", { signal })),
    refetchInterval: 60_000,
  });
  return (
    <ListCard title={t("title")} counted={t("hint")}>
      <div className="space-y-4 p-4">
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2 font-medium">
            <Activity className="size-4" />
            {query.isPending
              ? t("loading")
              : query.isError
                ? t("unavailable")
                : query.data.enabled
                  ? t("enabled")
                  : t("disabled")}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("refresh")}
            onClick={() => {
              void query.refetch();
            }}
          >
            <RefreshCw className="size-4" />
          </Button>
        </div>
        {query.data ? (
          <dl className="grid gap-2 text-sm">
            <div>
              <dt className="text-muted-foreground">{t("collector")}</dt>
              <dd className="break-all">{query.data.collector}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("lastSuccess")}</dt>
              <dd>
                {query.data.last_success === null
                  ? t("never")
                  : new Date(query.data.last_success * 1000).toLocaleString()}
              </dd>
            </div>
            {query.data.last_error ? (
              <div>
                <dt className="text-muted-foreground">{t("lastError")}</dt>
                <dd>{t(query.data.last_error)}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}
        <p className="text-muted-foreground text-sm">{t("scope")}</p>
        <p className="text-sm">
          {t("disable")}
          {/* i18n-exempt: literal environment setting, identical in every locale */}
          <code>DIAGNOSTICS_ENABLED=false</code>
        </p>
      </div>
    </ListCard>
  );
}
