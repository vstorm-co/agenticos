"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { appConnectionLabel, appConnectionUsable } from "@/lib/app-connection-journey";
import type { AppConnection } from "@/types/app-connections";
import { AppConnectionIcon } from "./app-connection-icon";

export function ConnectionAccounts({
  connections,
  busy,
  onReconnect,
  onRefresh,
  onDisconnect,
  onDefault,
  onEnable,
}: {
  connections: AppConnection[];
  busy: boolean;
  onReconnect: (connection: AppConnection) => void;
  onRefresh: (connection: AppConnection) => void;
  onDisconnect: (connection: AppConnection) => void;
  onDefault: (connection: AppConnection) => void;
  onEnable: (connection: AppConnection) => void;
}) {
  const t = useTranslations("appConnections");
  if (!connections.length) return null;
  return (
    <section className="space-y-3" aria-label={t("yourAccounts")}>
      <div>
        <h2 className="text-lg font-medium">{t("yourAccounts")}</h2>
        <p className="text-muted-foreground mt-1 text-sm">{t("personalHint")}</p>
      </div>
      <ul className="divide-border divide-y rounded-xl border px-4">
        {connections.map((connection) => {
          const app = connection.app;
          const usable = appConnectionUsable(connection);
          return (
            <li key={connection.id} className="flex flex-wrap items-start gap-3 py-4">
              <AppConnectionIcon toolkit={connection.toolkit} />
              <div className="min-w-0 flex-1 basis-40 space-y-1 break-words">
                <h3 className="text-sm font-medium">{app?.name ?? connection.toolkit}</h3>
                <p className="text-sm">{appConnectionLabel(connection)}</p>
                <p className="text-muted-foreground text-xs" role="status">
                  {t(`statuses.${connection.status}`)}
                  {connection.is_default ? ` · ${t("defaultAccount")}` : ""}
                </p>
                {usable && (
                  <p className="text-muted-foreground text-xs">{t("authorizationVerified")}</p>
                )}
                {connection.last_error && (
                  <p className="text-destructive text-xs">{t("checkFailed")}</p>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {!connection.is_enabled && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => onEnable(connection)}
                  >
                    {t("enable")}
                  </Button>
                )}
                {connection.is_enabled && !usable && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy || !app?.configured}
                    onClick={() => onReconnect(connection)}
                  >
                    {t("reconnect")}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => onRefresh(connection)}
                >
                  {t("checkConnection")}
                </Button>
                {usable && !connection.is_default && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => onDefault(connection)}
                  >
                    {t("makeDefault")}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => onDisconnect(connection)}
                >
                  {t("disconnect")}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      {connections.length > 1 && (
        <p className="text-muted-foreground text-xs">{t("defaultHint")}</p>
      )}
    </section>
  );
}
