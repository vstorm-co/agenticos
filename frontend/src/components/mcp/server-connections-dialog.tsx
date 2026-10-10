"use client";

import { useState } from "react";
import { Building2, History, Lock, Plug, User, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { AddToAgent } from "@/components/agents/add-to-agent";
import { UsedBy } from "@/components/agents/used-by";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import { McpCallLog } from "./mcp-call-log";

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { connectionState, MCP_STATE_LABEL } from "@/lib/mcp-servers";
import type { McpServerRow } from "@/lib/mcp-servers";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import { cn } from "@/lib/utils";
import type { Scope } from "./mcp-server-list-types";

/**
 * Every account on one server, and what each is for.
 *
 * The card that opens this carries two controls whatever it holds, because a
 * footer that grew a chip per connection made a server with three accounts
 * stand taller than its neighbours. The detail moves here, where there is room
 * to say the thing the card could not: which owner each account belongs to,
 * which decides where it can be used at all.
 *
 * Grouped under headings rather than distinguished by an icon, because that
 * distinction is not decoration. An organization's account is the only kind an
 * agent can be bound to; a person's is theirs alone, for their own chat and
 * their own direct messages.
 */
export function ServerConnectionsDialog({
  row,
  canManageOrganization,
  busyId,
  onClose,
  onConnect,
  onEdit,
  onTools,
  onDisconnect,
  onNominate,
  onOAuth,
}: {
  /** The server being managed, or null when the dialog is closed. */
  row: McpServerRow | null;
  canManageOrganization: boolean;
  busyId: string | null;
  onClose: () => void;
  onConnect: (scope: Scope, row: McpServerRow) => void;
  onEdit: (scope: Scope, row: McpServerRow, connection: McpConnectionRecord) => void;
  onTools: (scope: Scope, connection: McpConnectionRecord) => void;
  onDisconnect: (scope: Scope, connection: McpConnectionRecord) => void;
  /** Nominate one of the reader's own accounts. Personal connections only. */
  onNominate: (connection: McpConnectionRecord, use: boolean) => void;
  onOAuth: (scope: Scope, row: McpServerRow, connection: McpConnectionRecord) => void;
}) {
  const t = useTranslations("mcp");
  const [audienceOf, setAudienceOf] = useState<McpConnectionRecord | null>(null);
  const [callsOf, setCallsOf] = useState<McpConnectionRecord | null>(null);

  return (
    <>
      <Dialog open={row !== null} onOpenChange={(open) => !open && onClose()}>
        <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
          {row !== null && (
            <>
              <DialogHeader>
                <DialogTitle>{row.name}</DialogTitle>
                <DialogDescription>{t("accountsOnThisServer")}</DialogDescription>
              </DialogHeader>

              <div className="space-y-5">
                <Owners
                  heading={t("theOrganizations")}
                  caption={t("boundByAgents")}
                  icon={Building2}
                  connections={row.organizations}
                  // A viewer sees them and cannot act: the account is the
                  // organization's, and reading who holds it is not managing it.
                  readOnly={!canManageOrganization}
                  busyId={busyId}
                  onEdit={(connection) => onEdit("organization", row, connection)}
                  onTools={(connection) => onTools("organization", connection)}
                  onDisconnect={(connection) => onDisconnect("organization", connection)}
                  onOAuth={(connection) => onOAuth("organization", row, connection)}
                  onConnect={
                    canManageOrganization ? () => onConnect("organization", row) : undefined
                  }
                  onAudience={setAudienceOf}
                  onCalls={setCallsOf}
                  offerToAgents
                />
                <Owners
                  heading={t("yours")}
                  caption={t("yourChatAndDirectMessages")}
                  icon={User}
                  connections={row.personals}
                  readOnly={false}
                  busyId={busyId}
                  onEdit={(connection) => onEdit("personal", row, connection)}
                  onTools={(connection) => onTools("personal", connection)}
                  onDisconnect={(connection) => onDisconnect("personal", connection)}
                  onOAuth={(connection) => onOAuth("personal", row, connection)}
                  onConnect={() => onConnect("personal", row)}
                  // Only where there is a choice to make. One account is
                  // substituted whether or not it is marked, so a switch beside it
                  // would be a control that changes nothing (#1342).
                  onNominate={row.personals.length > 1 ? onNominate : undefined}
                />
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
      {callsOf !== null && <McpCallLog connection={callsOf} onClose={() => setCallsOf(null)} />}
      {/* Who sees and binds one of the organization's servers (#2072): the same
        panel as an agent's or a skill's, so a department narrows it the same way. */}
      <Dialog open={audienceOf !== null} onOpenChange={(open) => !open && setAudienceOf(null)}>
        <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
          {audienceOf !== null && (
            <>
              <DialogHeader>
                <DialogTitle>
                  {t("whoCanUseNamed", { name: audienceOf.label ?? audienceOf.name })}
                </DialogTitle>
                <DialogDescription>{t("whoCanUseHint")}</DialogDescription>
              </DialogHeader>
              <SharingPanel
                resourceType="mcp_connection"
                resourceId={audienceOf.id}
                canManage={canManageOrganization}
              />
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function Owners({
  heading,
  caption,
  icon: Icon,
  connections,
  readOnly,
  busyId,
  onEdit,
  onTools,
  onDisconnect,
  onOAuth,
  onConnect,
  onNominate,
  onAudience,
  onCalls,
  offerToAgents = false,
}: {
  heading: string;
  caption: string;
  icon: typeof Building2;
  connections: McpConnectionRecord[];
  readOnly: boolean;
  busyId: string | null;
  onEdit: (connection: McpConnectionRecord) => void;
  onTools: (connection: McpConnectionRecord) => void;
  onDisconnect: (connection: McpConnectionRecord) => void;
  onOAuth: (connection: McpConnectionRecord) => void;
  onNominate?: (connection: McpConnectionRecord, use: boolean) => void;
  onConnect?: () => void;
  /** Who sees and binds it - the organization's servers only (#2072). */
  onAudience?: (connection: McpConnectionRecord) => void;
  /** What agents asked it to do - the organization's servers only (#2072). */
  onCalls?: (connection: McpConnectionRecord) => void;
  /** Offer "Add to an agent" on each usable account: the organization's, which agents bind. */
  offerToAgents?: boolean;
}) {
  const t = useTranslations("mcp");

  return (
    <section className="space-y-2">
      <div>
        <h3 className="flex items-center gap-1.5 text-sm font-medium">
          <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {heading}
        </h3>
        <p className="text-muted-foreground text-xs">{caption}</p>
      </div>

      {connections.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("noneHere")}</p>
      ) : (
        <ul className="space-y-1.5">
          {connections.map((connection) => (
            <Account
              key={connection.id}
              connection={connection}
              readOnly={readOnly}
              busy={busyId === connection.id}
              onEdit={() => onEdit(connection)}
              onTools={() => onTools(connection)}
              onDisconnect={() => onDisconnect(connection)}
              onOAuth={() => onOAuth(connection)}
              onAudience={onAudience ? () => onAudience(connection) : undefined}
              onCalls={onCalls ? () => onCalls(connection) : undefined}
              offerToAgents={offerToAgents}
              onNominate={
                onNominate && connection.catalog_key !== null
                  ? (use) => onNominate(connection, use)
                  : undefined
              }
            />
          ))}
        </ul>
      )}

      {onConnect && (
        <Button size="sm" variant="outline" onClick={onConnect}>
          <Plug className="mr-1 h-3.5 w-3.5" />
          {connections.length === 0 ? t("connectAction") : t("connectAnother")}
        </Button>
      )}
    </section>
  );
}

function Account({
  connection,
  readOnly,
  busy,
  onEdit,
  onTools,
  onDisconnect,
  onOAuth,
  onNominate,
  onAudience,
  onCalls,
  offerToAgents = false,
}: {
  connection: McpConnectionRecord;
  readOnly: boolean;
  busy: boolean;
  onEdit: () => void;
  onTools: () => void;
  onDisconnect: () => void;
  onOAuth: () => void;
  /**
   * Passed only where the reader holds more than one account on this service
   * and this one names a catalog entry - the two conditions under which the
   * choice exists and can be recorded (#1342).
   */
  onNominate?: (use: boolean) => void;
  onAudience?: () => void;
  onCalls?: () => void;
  offerToAgents?: boolean;
}) {
  const t = useTranslations("mcp");
  const state = connectionState(connection);
  const narrowed = onAudience !== undefined && connection.visibility !== "org";

  return (
    <li className="border-border flex items-center gap-2 rounded-lg border px-3 py-2">
      <span
        aria-hidden
        className={cn(
          "inline-block h-2 w-2 shrink-0 rounded-full",
          state === "connected"
            ? "bg-success"
            : state === "error"
              ? "bg-destructive"
              : "bg-muted-foreground/50",
        )}
      />
      <span className="min-w-0 flex-1">
        {/* The label a person gave it, and always the slug underneath. Never
            the label alone: the slug is the prefix the model reads before it
            calls a tool, and a run's calls are recorded under it - so hiding it
            leaves "why did it call `notion-2_search`" unanswerable from the
            page that names the account. */}
        <span className="flex items-center gap-1.5 truncate text-sm">
          {connection.label ?? connection.name}
          {narrowed && (
            <span className="text-muted-foreground flex items-center gap-0.5 text-xs">
              <Lock className="h-3 w-3" aria-hidden />
              {t("narrowed")}
            </span>
          )}
        </span>
        <span className="text-muted-foreground text-xs">
          {connection.label === null ? (
            t(MCP_STATE_LABEL[state])
          ) : (
            <>
              <span className="font-mono">{connection.name}</span>
              {" · "}
              {t(MCP_STATE_LABEL[state])}
            </>
          )}
        </span>
        <UsedBy agents={connection.used_by ?? undefined} className="mt-0.5" />
        {offerToAgents && (state === "connected" || state === "error") && (
          <AddToAgent
            resource={{ kind: "mcp", id: connection.id }}
            name={connection.label ?? connection.name}
            className="mt-1 h-7"
          />
        )}
        {onNominate && (
          <label className="mt-1 flex items-center gap-1.5">
            <Checkbox
              checked={connection.is_default}
              disabled={busy}
              onCheckedChange={(next) => onNominate(next === true)}
            />
            <span className="text-muted-foreground text-xs">{t("agentsSpeakAsThisOne")}</span>
          </label>
        )}
      </span>

      {!readOnly && (
        <span className="flex shrink-0 items-center gap-1">
          {state === "needs-authorization" && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onOAuth}>
              {t("authorize")}
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={busy} onClick={onTools}>
            {t("tools")}
          </Button>
          {onCalls && (
            <Button
              size="icon"
              variant="ghost"
              className="h-8 w-8"
              disabled={busy}
              onClick={onCalls}
              aria-label={t("callLog")}
              title={t("callLog")}
            >
              <History className="h-4 w-4" />
            </Button>
          )}
          {onAudience && (
            <Button
              size="icon"
              variant="ghost"
              className="h-8 w-8"
              disabled={busy}
              onClick={onAudience}
              aria-label={t("whoCanUse")}
              title={t("whoCanUse")}
            >
              <Users className="h-4 w-4" />
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={busy} onClick={onEdit}>
            {t("edit")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive"
            disabled={busy}
            onClick={onDisconnect}
          >
            {t("disconnect")}
          </Button>
        </span>
      )}
    </li>
  );
}
