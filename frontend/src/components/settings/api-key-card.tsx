"use client";

import { KeyRound } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import { formatDate } from "@/lib/utils";
import type { ApiKey, ApiKeyStatus } from "@/types/api-keys";

export const STATUS_VARIANT: Record<ApiKeyStatus, "success" | "warning" | "destructive"> = {
  active: "success",
  expired: "warning",
  revoked: "destructive",
};

export function ApiKeyCard({
  apiKey: key,
  manages,
  onRevoke,
}: {
  apiKey: ApiKey;
  manages: boolean;
  onRevoke: (key: ApiKey) => void;
}) {
  const t = useTranslations("apiKeys");
  const locale = useLocale();
  return (
    <li className="min-w-0 rounded-xl border p-4">
      <div className="flex items-start gap-3">
        <span className="bg-muted text-muted-foreground grid size-9 shrink-0 place-items-center rounded-lg">
          <KeyRound className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold [overflow-wrap:anywhere]">{key.name}</h3>
          <p className="text-muted-foreground mt-1 font-mono text-xs">{key.prefix}…</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Badge variant={STATUS_VARIANT[key.status]}>{t(`state.${key.status}`)}</Badge>
        <span className="text-muted-foreground text-xs">
          {t("scopeCount", { count: key.scopes.length })}
        </span>
      </div>
      <dl className="mt-3 grid gap-2 text-xs">
        {manages && (
          <div className="space-y-0.5">
            <dt className="text-muted-foreground">{t("issuer")}</dt>
            <dd className="[overflow-wrap:anywhere]">{key.issuer_email}</dd>
          </div>
        )}
        <div className="flex flex-wrap justify-between gap-x-3 gap-y-1">
          <dt className="text-muted-foreground">{t("expires")}</dt>
          <dd>{key.expires_at ? formatDate(key.expires_at, locale) : t("noExpiry")}</dd>
        </div>
        <div className="flex flex-wrap justify-between gap-x-3 gap-y-1">
          <dt className="text-muted-foreground">{t("lastUsed")}</dt>
          <dd>{key.last_used_at ? formatDate(key.last_used_at, locale) : t("never")}</dd>
        </div>
      </dl>
      {key.status === "active" && (
        <Button className="mt-4 w-full" size="sm" variant="outline" onClick={() => onRevoke(key)}>
          {t("revoke")}
        </Button>
      )}
    </li>
  );
}
