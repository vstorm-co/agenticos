"use client";

import { useState } from "react";
import {
  Building2,
  ExternalLink,
  History,
  Lock,
  MoreHorizontal,
  Pencil,
  Plug,
  Radar,
  Plus,
  Unplug,
  User,
  Users,
  Wrench,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { AddToAgent } from "@/components/agents/add-to-agent";
import { WatchDialog } from "@/components/watches/watch-dialog";
import { UsedBy } from "@/components/agents/used-by";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import { McpCallLog } from "./mcp-call-log";
import { McpServerIcon } from "./mcp-server-icon";

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { useOrganizations } from "@/hooks";
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
  // One of the reader's own accounts to watch (#2301), where the organization allows it.
  const [watchOf, setWatchOf] = useState<McpConnectionRecord | null>(null);
  const { activeOrg } = useOrganizations();
  const watchable = activeOrg?.proactive_watches_enabled === true;

  return (
    <>
      <Dialog open={row !== null} onOpenChange={(open) => !open && onClose()}>
        <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
          {row !== null && (
            <>
              {/* Left-aligned on a phone too: a centred title beside a logo reads
                  as two things that missed each other. */}
              <DialogHeader className="min-w-0 text-left sm:text-left">
                <div className="flex items-center gap-3">
                  {/* The service's own mark, on the white tile its card draws it on:
                      the logos are made for a light ground. */}
                  <ServerMark row={row} className="size-10" />
                  <div className="min-w-0">
                    <DialogTitle>{row.name}</DialogTitle>
                    {/* The documentation on the line it belongs to, rather than a
                        lone link under the sentence it finishes. */}
                    <DialogDescription>
                      {t("accountsOnThisServer")}
                      {row.docsUrl && (
                        <>
                          {" "}
                          <a
                            href={row.docsUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="hover:text-foreground inline-flex items-center gap-0.5 whitespace-nowrap underline underline-offset-4"
                          >
                            {t("documentation")}
                            <ExternalLink className="h-3 w-3" aria-hidden />
                          </a>
                        </>
                      )}
                    </DialogDescription>
                  </div>
                </div>
              </DialogHeader>

              {/* `min-w-0`: a grid child keeps its content's width otherwise, and on
                  a phone that pushed every row past the dialog's edge. */}
              <div className="min-w-0 space-y-5">
                <Owners
                  row={row}
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
                  row={row}
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
                  onWatch={watchable ? setWatchOf : undefined}
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
      {watchOf !== null && (
        <WatchDialog
          open
          onOpenChange={(open) => !open && setWatchOf(null)}
          connectionId={watchOf.id}
        />
      )}
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
  row,
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
  onWatch,
  offerToAgents = false,
}: {
  row: McpServerRow;
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
  /** Have the platform watch it - the reader's own accounts only (#2301). */
  onWatch?: (connection: McpConnectionRecord) => void;
  /** Offer "Add to an agent" on each usable account: the organization's, which agents bind. */
  offerToAgents?: boolean;
}) {
  const t = useTranslations("mcp");

  return (
    <section className="space-y-2.5">
      {/* Adding an account sits on the heading it adds to, so "another" never
          has to be explained: the button is beside the list it grows. */}
      <div className="flex items-start gap-3">
        <span className="bg-muted text-muted-foreground grid size-8 shrink-0 place-items-center rounded-lg">
          <Icon className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">{heading}</h3>
          <p className="text-muted-foreground text-xs">{caption}</p>
        </div>
        {onConnect && (
          <Button size="sm" variant="outline" onClick={onConnect} className="shrink-0">
            {connections.length === 0 ? (
              <Plug className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <Plus className="h-3.5 w-3.5" aria-hidden />
            )}
            {connections.length === 0 ? t("connectAction") : t("connectAnother")}
          </Button>
        )}
      </div>

      {connections.length === 0 ? (
        <p className="border-border text-muted-foreground rounded-lg border border-dashed px-3 py-3 text-center text-xs">
          {t("noneHere")}
        </p>
      ) : (
        <ul className="space-y-2">
          {connections.map((connection) => (
            <Account
              key={connection.id}
              row={row}
              connection={connection}
              readOnly={readOnly}
              busy={busyId === connection.id}
              onEdit={() => onEdit(connection)}
              onTools={() => onTools(connection)}
              onDisconnect={() => onDisconnect(connection)}
              onOAuth={() => onOAuth(connection)}
              onAudience={onAudience ? () => onAudience(connection) : undefined}
              onCalls={onCalls ? () => onCalls(connection) : undefined}
              onWatch={onWatch ? () => onWatch(connection) : undefined}
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
    </section>
  );
}

/** The server's mark on a white tile, as its card draws it. */
function ServerMark({ row, className }: { row: McpServerRow; className?: string }) {
  return (
    <span
      className={cn(
        "border-foreground/10 grid shrink-0 place-items-center rounded-xl border bg-white",
        className,
      )}
    >
      <McpServerIcon
        icon={row.entry?.icon ?? null}
        name={row.name}
        url={row.url}
        className="size-[60%] text-neutral-900"
      />
    </span>
  );
}

function Account({
  row,
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
  onWatch,
  offerToAgents = false,
}: {
  row: McpServerRow;
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
  onWatch?: () => void;
  offerToAgents?: boolean;
}) {
  const t = useTranslations("mcp");
  const state = connectionState(connection);
  const narrowed = onAudience !== undefined && connection.visibility !== "org";

  return (
    <li className="border-border flex items-center gap-3 rounded-xl border px-3 py-2.5">
      <span className="relative shrink-0">
        <ServerMark row={row} className="size-8 rounded-lg" />
        {/* The state as a dot on the mark, the way a person's presence is on
            their face: green connected, red refused, grey waiting. */}
        <span
          aria-hidden
          className={cn(
            "ring-background absolute -right-0.5 -bottom-0.5 h-2.5 w-2.5 rounded-full ring-2",
            state === "connected"
              ? "bg-success"
              : state === "error"
                ? "bg-destructive"
                : "bg-muted-foreground/50",
          )}
        />
      </span>
      <span className="min-w-0 flex-1">
        {/* The label a person gave it, and always the slug underneath. Never
            the label alone: the slug is the prefix the model reads before it
            calls a tool, and a run's calls are recorded under it - so hiding it
            leaves "why did it call `notion-2_search`" unanswerable from the
            page that names the account. */}
        <span className="flex items-center gap-1.5 truncate text-sm font-medium">
          {connection.label ?? connection.name}
          {narrowed && (
            <span className="text-muted-foreground flex items-center gap-0.5 text-xs font-normal">
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
            <span className="text-muted-foreground text-xs">{t("mainAccount")}</span>
          </label>
        )}
      </span>

      {!readOnly && (
        // One action in sight - the one this account needs next - and the rest
        // behind a menu: six controls in a row made every account look like a
        // toolbar, and the red Disconnect was the loudest thing on it.
        <span className="flex shrink-0 items-center gap-1">
          {state === "needs-authorization" ? (
            <Button size="sm" variant="outline" disabled={busy} onClick={onOAuth}>
              {t("authorize")}
            </Button>
          ) : (
            <>
              {/* Beside Tools rather than in the menu: a watch is something to
                  offer, and nobody looked for it behind the dots (#2301). */}
              {onWatch && state === "connected" && (
                <Button size="sm" variant="outline" disabled={busy} onClick={onWatch}>
                  <Radar className="h-3.5 w-3.5" aria-hidden />
                  {t("watch")}
                </Button>
              )}
              <Button size="sm" variant="outline" disabled={busy} onClick={onTools}>
                {t("tools")}
              </Button>
            </>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                disabled={busy}
                aria-label={t("accountActions", { name: connection.label ?? connection.name })}
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              {state === "needs-authorization" && (
                <DropdownMenuItem onSelect={onTools}>
                  <Wrench className="h-4 w-4" aria-hidden />
                  {t("tools")}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={onEdit}>
                <Pencil className="h-4 w-4" aria-hidden />
                {t("edit")}
              </DropdownMenuItem>
              {onAudience && (
                <DropdownMenuItem onSelect={onAudience}>
                  <Users className="h-4 w-4" aria-hidden />
                  {t("whoCanUse")}
                </DropdownMenuItem>
              )}
              {onCalls && (
                <DropdownMenuItem onSelect={onCalls}>
                  <History className="h-4 w-4" aria-hidden />
                  {t("callLog")}
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={onDisconnect}
                className="text-destructive focus:text-destructive"
              >
                <Unplug className="h-4 w-4" aria-hidden />
                {t("disconnect")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </span>
      )}
    </li>
  );
}
