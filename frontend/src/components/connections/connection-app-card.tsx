"use client";

import { useTranslations } from "next-intl";
import { Badge, Button } from "@/components/ui";
import type { ConnectedAppDefinition } from "@/types/app-connections";
import { AppConnectionIcon } from "./app-connection-icon";

export function ConnectionAppCard({
  app,
  recommended,
  connected,
  busy,
  onConnect,
}: {
  app: ConnectedAppDefinition;
  recommended: boolean;
  connected: boolean;
  busy: boolean;
  onConnect: (app: ConnectedAppDefinition) => void;
}) {
  const t = useTranslations("appConnections");
  return (
    <article className="border-border flex min-w-0 flex-col gap-4 rounded-xl border p-4">
      <div className="flex items-start gap-3">
        <AppConnectionIcon toolkit={app.toolkit} />
        <div className="min-w-0 space-y-1">
          <h3 className="text-sm font-medium">{app.name}</h3>
          {recommended && <Badge variant="secondary">{t("recommended")}</Badge>}
          <p className="text-muted-foreground line-clamp-3 text-sm">
            {t.has(`toolkits.${app.toolkit}`) ? t(`toolkits.${app.toolkit}`) : app.description}
          </p>
        </div>
      </div>
      <div className="mt-auto space-y-2">
        {app.configured && app.approval_required && (
          <p className="text-muted-foreground text-xs">{t("approvalRequired")}</p>
        )}
        {!app.configured && (
          <p className="text-muted-foreground text-xs">
            {t(app.availability === "unavailable" ? "unavailableAppHint" : "setupRequiredHint")}
          </p>
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={busy || !app.configured}
          aria-label={t("connectNamed", { name: app.name })}
          onClick={() => onConnect(app)}
        >
          {app.configured
            ? t(connected ? "addAccount" : "connect")
            : t(app.availability === "unavailable" ? "unavailableApp" : "notConfigured")}
        </Button>
      </div>
    </article>
  );
}
