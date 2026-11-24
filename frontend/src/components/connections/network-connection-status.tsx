"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import type { NetworkConnection } from "@/types/network-connections";

export function NetworkConnectionStatus({ connection }: { connection: NetworkConnection }) {
  const t = useTranslations("networkConnections");
  const authVariant =
    connection.auth_state === "authenticated"
      ? "success"
      : connection.auth_state === "error" || connection.auth_state === "expired"
        ? "destructive"
        : connection.auth_state === "sign_in_required" ||
            connection.auth_state === "approval_required"
          ? "warning"
          : "outline";
  const runtimeVariant =
    connection.runtime_state === "running"
      ? "success"
      : connection.runtime_state === "unavailable"
        ? "destructive"
        : connection.runtime_state === "starting"
          ? "warning"
          : "outline";

  return (
    <div className="flex flex-wrap gap-2" aria-label={t("status.groupLabel")}>
      {connection.desired_state === "paused" && (
        <Badge variant="warning">{t("status.paused")}</Badge>
      )}
      {connection.desired_state === "revoked" && (
        <Badge variant="destructive">{t("status.revoked")}</Badge>
      )}
      <Badge variant={authVariant}>{t(`status.auth.${connection.auth_state}`)}</Badge>
      <Badge variant={runtimeVariant}>{t(`status.runtime.${connection.runtime_state}`)}</Badge>
      {connection.cleanup_state === "pending" && (
        <Badge variant="warning">{t("cleanup.pending")}</Badge>
      )}
      {connection.cleanup_state === "manual" && (
        <Badge variant="destructive">{t("cleanup.manual")}</Badge>
      )}
      {connection.cleanup_state === "complete" && (
        <Badge variant="success">{t("cleanup.complete")}</Badge>
      )}
    </div>
  );
}
