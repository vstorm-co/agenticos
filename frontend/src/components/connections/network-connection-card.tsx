"use client";

import { useState } from "react";
import { Network, Pause, Play, RefreshCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import type { NetworkConnection, NetworkConnectionScopeKey } from "@/types/network-connections";
import { NetworkConnectionPeers } from "./network-connection-peers";
import { NetworkConnectionStatus } from "./network-connection-status";

export function NetworkConnectionCard({
  connection,
  scope,
  available,
  busy,
  connectTour,
  onConnect,
  onPause,
  onRefreshStatus,
  onRevoke,
}: {
  connection: NetworkConnection;
  scope: NetworkConnectionScopeKey | null;
  available: boolean | null;
  busy: boolean;
  connectTour?: string;
  onConnect: (connection: NetworkConnection) => void;
  onPause: (connection: NetworkConnection) => void;
  onRefreshStatus: (connection: NetworkConnection) => void;
  onRevoke: (connection: NetworkConnection) => Promise<boolean>;
}) {
  const t = useTranslations("networkConnections");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const canManage = connection.can_manage;
  const canEnroll =
    connection.desired_state !== "revoked" &&
    (connection.desired_state === "paused" || connection.auth_state !== "authenticated");
  const resume = connection.desired_state === "paused" && connection.auth_state === "authenticated";
  const canRefresh =
    canManage &&
    available === true &&
    connection.desired_state === "active" &&
    connection.auth_state === "authenticated" &&
    connection.runtime_state === "stopped";
  const connectLabel = resume
    ? t("actions.resume")
    : connection.auth_state === "sign_in_required"
      ? t("actions.continueSignIn")
      : connection.auth_state === "approval_required"
        ? t("actions.continueApproval")
        : t("actions.connectDevice");

  return (
    <article className="border-border min-w-0 space-y-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-lg">
            <Network className="size-5" aria-hidden />
          </span>
          <div className="min-w-0 space-y-1">
            <h2 className="text-sm font-medium break-words">{connection.name}</h2>
            <p className="text-muted-foreground text-xs">
              {t(`scope.${connection.scope}`)}
              {connection.tailnet_name ? ` · ${connection.tailnet_name}` : ""}
            </p>
          </div>
        </div>
        <NetworkConnectionStatus connection={connection} />
      </div>

      {connection.auth_state === "authenticated" &&
        connection.runtime_state === "stopped" &&
        connection.desired_state === "active" && (
          <p role="status" className="bg-muted text-muted-foreground rounded-lg p-3 text-sm">
            {t("enrollment.enrolledIdle")}
          </p>
        )}
      {connection.last_seen_at && (
        <p className="text-muted-foreground text-xs">
          {t("lastSeen", { time: new Date(connection.last_seen_at).toLocaleString() })}
        </p>
      )}
      {connection.cleanup_state === "manual" && (
        <p
          role="note"
          className="border-destructive/30 bg-destructive/5 rounded-lg border p-3 text-sm"
        >
          {t("cleanup.manualInstructions")}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {canEnroll && canManage && (
          <Button
            data-tour={connectTour ?? "network-connect-actions"}
            variant={resume ? "default" : "outline"}
            size="sm"
            disabled={busy || available !== true}
            onClick={() => onConnect(connection)}
          >
            {resume ? <Play aria-hidden /> : <Network aria-hidden />}
            {connectLabel}
          </Button>
        )}
        {connection.desired_state === "active" && canManage && (
          <Button variant="outline" size="sm" disabled={busy} onClick={() => onPause(connection)}>
            <Pause aria-hidden />
            {t("actions.pause")}
          </Button>
        )}
        {canManage && connection.desired_state !== "revoked" && (
          <Button variant="outline" size="sm" disabled={busy} onClick={() => setConfirmOpen(true)}>
            <Trash2 aria-hidden />
            {t("actions.revoke")}
          </Button>
        )}
        {canRefresh && (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => onRefreshStatus(connection)}
          >
            <RefreshCw aria-hidden />
            {t("refreshStatus")}
          </Button>
        )}
        {!canManage && <Badge variant="secondary">{t("readOnly")}</Badge>}
      </div>

      {connection.auth_state === "authenticated" && connection.desired_state !== "revoked" && (
        <NetworkConnectionPeers id={connection.id} scope={scope} />
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={t("revoke.title", { name: connection.name })}
        description={t("revoke.description")}
        confirmLabel={t("actions.revoke")}
        destructive
        loading={busy}
        onConfirm={async () => {
          if (await onRevoke(connection)) setConfirmOpen(false);
        }}
      />
    </article>
  );
}
