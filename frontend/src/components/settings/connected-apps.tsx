"use client";

import { useState } from "react";
import { PlugZap } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState, ErrorState } from "@/components/states";
import { Button, ConfirmDialog, DataTable, type Column } from "@/components/ui";
import { useConnectedApps, usePermissions } from "@/hooks";
import { formatDate } from "@/lib/utils";
import type { ConnectedApp } from "@/types/mcp-oauth";
import { Perm } from "@/types/permissions";

/**
 * Applications connected through OAuth - Claude Code signed in through the
 * browser, say - and the control that disconnects one, revoking every token it
 * holds at once (#2059).
 */
export function ConnectedApps() {
  const t = useTranslations("mcpOauth");
  const tc = useTranslations("common");
  const locale = useLocale();
  const { can } = usePermissions();
  const { apps, isLoading, error, refetch, disconnect } = useConnectedApps();
  const [leaving, setLeaving] = useState<ConnectedApp | null>(null);

  const columns: Column<ConnectedApp>[] = [
    {
      key: "name",
      header: t("application"),
      cell: (app) => <span className="text-sm font-medium">{app.client_name}</span>,
    },
    {
      key: "scopes",
      header: t("access"),
      cell: (app) => (
        <span className="text-muted-foreground font-mono text-xs" title={app.scopes.join(", ")}>
          {t("scopeCount", { count: app.scopes.length })}
        </span>
      ),
      hideBelow: "md",
    },
    ...(can(Perm.apiKeysManage)
      ? [
          {
            key: "user",
            header: t("connectedBy"),
            cell: (app: ConnectedApp) => <span className="text-xs">{app.user_email}</span>,
            hideBelow: "lg" as const,
          },
        ]
      : []),
    {
      key: "since",
      header: t("since"),
      cell: (app) => (
        <span className="text-muted-foreground text-xs">{formatDate(app.created_at, locale)}</span>
      ),
      hideBelow: "sm",
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (app) => (
        <Button size="sm" variant="outline" onClick={() => setLeaving(app)}>
          {t("disconnect")}
        </Button>
      ),
    },
  ];

  return (
    <section className="border-border bg-card rounded-xl border" data-tour="connected-apps">
      <header className="border-border border-b px-5 py-4">
        <h2 className="text-foreground text-sm font-semibold">{t("connectedTitle")}</h2>
        <p className="text-muted-foreground mt-1 text-xs">{t("connectedWhy")}</p>
      </header>
      <div className="px-5 py-5">
        <DataTable
          columns={columns}
          rows={apps}
          getRowKey={(app) => app.id}
          loading={isLoading}
          error={
            error ? (
              <ErrorState
                title={t("couldNotLoad")}
                cta={{ label: tc("retry"), onClick: () => void refetch() }}
              />
            ) : undefined
          }
          empty={<EmptyState icon={PlugZap} title={t("emptyTitle")} description={t("emptyWhy")} />}
        />
      </div>
      {leaving && (
        <ConfirmDialog
          open
          onOpenChange={() => setLeaving(null)}
          title={t("disconnectTitle", { client: leaving.client_name })}
          description={t("disconnectWhy")}
          confirmLabel={t("disconnect")}
          destructive
          loading={disconnect.isPending}
          onConfirm={async () => {
            await disconnect.mutateAsync(leaving.id);
            setLeaving(null);
          }}
        />
      )}
    </section>
  );
}
