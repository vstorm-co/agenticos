"use client";

import { useState } from "react";

import { McpBindingDialog } from "@/components/agents/mcp-binding-dialog";
import { useBranding } from "@/components/branding/branding-provider";
import { CardStatus, McpServerCard } from "@/components/mcp/mcp-server-card";
import { PlatformServerCard } from "./platform-server-card";
import { Checkbox, Pager, SearchInput, Switch, useListControls } from "@/components/ui";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import { entryForConnection } from "@/lib/mcp-servers";
import type { McpConnectionRecord, McpToolInfo } from "@/lib/mcp-connections-api";
import type { AccountRef } from "@/components/agents/mcp-binding-dialog";
import type { McpServerRef, PlatformMcpServerRef } from "@/types/agents";
import type { McpCatalogEntry } from "@/types/mcp";
import { useTranslations } from "next-intl";

/**
 * What identifies a binding in the spec: the connection it names, or the
 * service each person reaches through their own account.
 *
 * Two bindings with one key are the same binding, which is what the Builder
 * needs to replace a binding's tools without knowing which kind it is.
 */
export function bindingKey(ref: McpServerRef): string {
  if (ref.account === "platform") return "platform";
  return ref.account === "personal"
    ? `personal:${ref.catalog_key}`
    : `organization:${ref.connection_id}`;
}

interface McpServerPickerProps {
  /** The organization's servers - what an organization binding may name. */
  connections: OrgMcpConnectionRecord[];
  /** The organization catalog: every server that can be connected in one click. */
  catalog: McpCatalogEntry[];
  /** `spec.mcp_servers`. */
  value: McpServerRef[];
  /**
   * The whole list, rebuilt.
   *
   * One callback rather than one per gesture. Binding, choosing which account
   * and switching a binding between the organization's account and each
   * person's own all write the same list, and three callbacks reading the same
   * spec would each start from the copy the previous one replaced.
   */
  onChange: (next: McpServerRef[]) => void;
  /**
   * Choose which of a server's tools this agent may call.
   *
   * The dialog is the caller's, like `onConnect`. The tool list comes from an
   * organization connection's last probe, which is why one is handed over even
   * for a binding to each person's own account: the catalogue of tools is the
   * server's, whoever's credential reaches it.
   */
  onTools: (ref: McpServerRef, probed: OrgMcpConnectionRecord, name: string) => void;
  /**
   * Connect a server that has none, without leaving the page.
   *
   * The dialog is the caller's rather than this component's: the picker is
   * handed its connections and catalog and renders them, and a data hook inside
   * it would make a presentational component fetch.
   */
  onConnect: (entry: McpCatalogEntry) => void;
  /**
   * The reader's own MCP connections, for the tools of a server the organization
   * holds no connection to - listed from their own account's last check.
   */
  personalConnections?: McpConnectionRecord[];
  /** Connect the reader's own account on a catalog server, without leaving the page. */
  onConnectOwn?: (entry: McpCatalogEntry) => void;
  /** Disconnect one of the reader's own accounts, from a server's settings. */
  onDisconnectOwn?: (connection: McpConnectionRecord) => void;
  /** Sign one of the reader's own accounts in again. */
  onSignInOwn?: (connection: McpConnectionRecord) => void;
  /** The connect form with its settings open, for a server **Connect** signs straight in to. */
  onConfigure?: (entry: McpCatalogEntry, scope: "organization" | "personal") => void;
  disabled?: boolean;
}

/**
 * Attach MCP servers to an agent, against the whole catalog.
 *
 * The gallery shows every server the platform can connect, not only the ones
 * that already have credentials. Showing the connected subset answered "what
 * can I attach right now" and left "what could this agent reach at all"
 * unanswerable without leaving the page - and a catalog nobody sees is a
 * catalog nobody connects from.
 *
 * A binding is one of two kinds, and the card's settings ask which - for each
 * of the accounts the agent reaches the server through, since one agent may
 * read two mailboxes at once (#2125). **The organization's
 * account** names one of the organization's connections and answers for
 * everybody - the reviewable default. **Each person's own account** names the
 * catalog service instead: whoever talks to the agent connects their own, and
 * the agent speaks to the service as them. The second needs no connection to
 * exist here, which is why an unconnected server still offers it. A member's
 * connection is never bound directly - `validate_spec` refuses one at publish -
 * because what a published agent reaches must not depend on who happened to
 * build it.
 *
 * Ids in the spec that match no connection are shown rather than dropped: they
 * belong to a server that has since been removed, or to another organization in
 * an imported spec, and an id that quietly vanishes from a form is an id that
 * quietly vanishes from the spec.
 */
export function McpServerPicker({
  connections,
  catalog,
  value,
  onChange,
  onTools,
  onConnect,
  personalConnections = [],
  onConnectOwn,
  onDisconnectOwn,
  onSignInOwn,
  onConfigure,
  disabled,
}: McpServerPickerProps) {
  const t = useTranslations("agents");
  const { appName } = useBranding();
  const [connectedOnly, setConnectedOnly] = useState(false);
  const known = new Set(connections.map((connection) => connection.id));
  const catalogKeys = new Set(catalog.map((entry) => entry.key));
  // Of either kind: an organization binding to a connection this organization no
  // longer holds, and a personal one to a key the catalog no longer describes.
  // A card can match neither, so unlisted they would vanish from the Builder
  // while publish kept refusing them.
  // The platform's own server is never orphaned: it is this deployment.
  const orphaned = value.flatMap((ref) =>
    ref.account === "platform"
      ? []
      : ref.account === "organization"
        ? known.has(ref.connection_id)
          ? []
          : [ref.connection_id]
        : catalogKeys.has(ref.catalog_key)
          ? []
          : [ref.catalog_key],
  );

  const platform =
    value.find((ref): ref is PlatformMcpServerRef => ref.account === "platform") ?? null;

  /** Replace every binding this row held with `next` - several, one, or none. */
  const rebind = (row: CardRow, next: AccountRef[]) => {
    const mine = new Set<McpServerRef>(bindingsFor(row, value));
    onChange([...value.filter((ref) => !mine.has(ref)), ...next]);
  };

  // A connection the catalog does not describe is a custom server somebody
  // pointed at a URL. It belongs on the gallery under its own name rather than
  // nowhere, so the rows are built from both sides and then merged.
  //
  // One row per *server*, holding every connection to it. A row per connection
  // was tried and produced two identical cards for one Notion, which reads as a
  // bug rather than as two accounts - so the row carries the list and the card
  // asks which account when there is a choice (#1341).
  const described = new Map<string, OrgMcpConnectionRecord[]>();
  const custom: OrgMcpConnectionRecord[] = [];
  for (const connection of connections) {
    const entry = entryForConnection(connection, catalog);
    if (entry) described.set(entry.key, [...(described.get(entry.key) ?? []), connection]);
    else custom.push(connection);
  }

  const rows: CardRow[] = [
    ...catalog.map((entry): CardRow => {
      const owned = described.get(entry.key) ?? [];
      return {
        key: entry.key,
        name: entry.name,
        description: entry.description,
        icon: entry.icon,
        entry,
        connections: owned,
      };
    }),
    ...custom.map((connection): CardRow => ({
      key: connection.id,
      name: connection.name,
      description: connection.url,
      icon: null,
      entry: null,
      connections: [connection],
    })),
  ];

  const narrowed = connectedOnly ? rows.filter((row) => row.connections.length > 0) : rows;
  const list = useListControls({
    items: narrowed,
    // More than the default fifty, and a multiple of four, three and two, so
    // every width of the grid ends its page on a full row.
    pageSize: 60,
    matches: (row, query) =>
      row.name.toLowerCase().includes(query) || row.description.toLowerCase().includes(query),
  });

  // The built-in card answers a search as the catalog's do, so a query matching
  // none of them does not leave it standing beside "no matches".
  const query = list.query.trim().toLowerCase();
  const platformMatches =
    query === "" ||
    [appName, t("platformServerDescription")].some((text) => text.toLowerCase().includes(query));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={list.query} onChange={list.setQuery} placeholder={t("searchServers")} />
        {/* The catalog is mostly servers nobody has connected. Hiding them is
            the filter this picker needs when the organization's account is what
            is being bound; a binding to each person's own account is offered
            either way. */}
        <label className="text-muted-foreground flex items-center gap-2 text-sm">
          <Checkbox
            checked={connectedOnly}
            onCheckedChange={(next) => setConnectedOnly(next === true)}
          />
          {t("connectedOnly")}
        </label>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {/* First, and on every page a search does not rule out: the one server
            that needs no connection, because it is this deployment (#2190). */}
        {list.page === 0 && !connectedOnly && platformMatches && (
          <PlatformServerCard
            binding={platform}
            onChange={(next) =>
              onChange([
                ...value.filter((ref) => ref.account !== "platform"),
                ...(next === null ? [] : [next]),
              ])
            }
            disabled={disabled}
          />
        )}
        {list.visible.map((row) => (
          <ServerCard
            key={row.key}
            row={row}
            bindings={bindingsFor(row, value)}
            onRebind={(next) => rebind(row, next)}
            onTools={onTools}
            onConnect={onConnect}
            personalTools={
              personalConnections.find(
                (connection) =>
                  connection.catalog_key === row.entry?.key && connection.last_tools !== null,
              )?.last_tools ?? null
            }
            ownAccounts={personalConnections.filter(
              (connection) => connection.catalog_key === row.entry?.key,
            )}
            onDisconnectOwn={onDisconnectOwn}
            onSignInOwn={onSignInOwn}
            onConnectOwn={onConnectOwn}
            onConfigure={onConfigure}
            disabled={disabled}
          />
        ))}
      </div>

      <Pager
        page={list.page}
        pageCount={list.pageCount}
        matched={list.matched}
        total={list.total}
        onPage={list.setPage}
        counted={t("serverCount", { count: list.total })}
      />

      <OrphanedIds ids={orphaned} />
    </div>
  );
}

/** One card's worth of a server, whether the catalog described it or not. */
interface CardRow {
  key: string;
  name: string;
  description: string;
  icon: string | null;
  /**
   * Every account the organization holds on this server.
   *
   * Empty means the organization's account cannot be bound - the card offers to
   * connect one instead, beside binding each person's own. More than one means
   * the card asks *which*, because an organization binding names a connection
   * and the answer to "whose credential is this" has to be on screen.
   */
  connections: OrgMcpConnectionRecord[];
  /** The catalog entry behind the row, so an unconnected one can be connected. */
  entry: McpCatalogEntry | null;
}

/**
 * Every binding the spec holds for this row, of either kind - the same server
 * may be reached through several accounts at once (#2125).
 */
function bindingsFor(row: CardRow, value: McpServerRef[]): AccountRef[] {
  const ids = new Set(row.connections.map((connection) => connection.id));
  return value.filter(
    (ref): ref is AccountRef =>
      (ref.account === "organization" && ids.has(ref.connection_id)) ||
      (ref.account === "personal" && row.entry !== null && ref.catalog_key === row.entry.key),
  );
}

function ServerCard({
  row,
  bindings,
  onRebind,
  onTools,
  onConnect,
  personalTools,
  ownAccounts,
  onDisconnectOwn,
  onSignInOwn,
  onConnectOwn,
  onConfigure,
  disabled,
}: {
  row: CardRow;
  bindings: AccountRef[];
  onRebind: (next: AccountRef[]) => void;
  onTools: (ref: McpServerRef, probed: OrgMcpConnectionRecord, name: string) => void;
  onConnect: (entry: McpCatalogEntry) => void;
  personalTools: McpToolInfo[] | null;
  /** The reader's own accounts on the server. */
  ownAccounts: McpConnectionRecord[];
  onDisconnectOwn?: (connection: McpConnectionRecord) => void;
  onSignInOwn?: (connection: McpConnectionRecord) => void;
  onConnectOwn?: (entry: McpCatalogEntry) => void;
  onConfigure?: (entry: McpCatalogEntry, scope: "organization" | "personal") => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  const tMcp = useTranslations("mcp");
  const { name, description, icon, connections, entry } = row;
  // Only a server that signs in: its **Connect** goes straight to the provider,
  // and this is the way to the form. One taking a token opens the form anyway.
  const configure =
    entry !== null && entry.auth === "oauth" && onConfigure
      ? (scope: "organization" | "personal") => onConfigure(entry, scope)
      : undefined;
  const boundIds = new Set(
    bindings.flatMap((ref) => (ref.account === "organization" ? [ref.connection_id] : [])),
  );
  // The account the card reports on: the first one bound, else the first held.
  const connection =
    connections.find((account) => boundIds.has(account.id)) ?? connections[0] ?? null;
  const isOn = bindings.length > 0;
  const onlyPersonal = isOn && boundIds.size === 0;
  const orgBindable = connection !== null;
  // A server the catalog does not describe has no key for a person's own
  // connection to be matched on, so only an organization's can be bound.
  const personalBindable = entry !== null;

  const [settingsOpen, setSettingsOpen] = useState(false);
  // Switched on, a card binds the organization's account where there is one and
  // each person's own where there is not - the one kind that needs no connection
  // to exist - and opens its settings, because which accounts and which tools
  // is the next thing to decide. Off unbinds every account it had.
  const toggle = (on: boolean) => {
    if (!on) {
      onRebind([]);
      return;
    }
    if (connection) {
      onRebind([{ account: "organization", connection_id: connection.id, allowed_tools: null }]);
    } else if (entry) {
      onRebind([{ account: "personal", catalog_key: entry.key, allowed_tools: null }]);
    }
    setSettingsOpen(true);
  };

  return (
    <>
      <McpServerCard
        name={name}
        icon={icon}
        url={entry?.url ?? connection?.url ?? null}
        description={description}
        headerAction={
          <Switch
            checked={isOn}
            disabled={disabled || (!orgBindable && !personalBindable)}
            onCheckedChange={toggle}
            aria-label={t("useServerInAgent", { name })}
          />
        }
        // One line in the same place on every card: how this agent reaches the
        // server when it uses it, and otherwise who could connect it. Whose
        // account, which tools and connecting one are all in its settings,
        // which the card opens, so no card carries a button another lacks.
        status={
          isOn ? (
            <CardStatus
              tone="live"
              onClick={disabled ? undefined : () => setSettingsOpen(true)}
              label={t("serverSettingsNamed", { name })}
            >
              {bindings.length > 1
                ? t("accountCount", { count: bindings.length })
                : onlyPersonal
                  ? t("eachPersonsOwnAccount")
                  : t("cardOrganizationsAccount", {
                      name: connection?.label ?? connection?.name ?? name,
                    })}
            </CardStatus>
          ) : (
            <CardStatus
              tone="off"
              onClick={disabled ? undefined : () => setSettingsOpen(true)}
              label={t("serverSettingsNamed", { name })}
            >
              {orgBindable
                ? t("cardOrganizationConnected")
                : ownAccounts.length > 0
                  ? t("cardYourAccountConnected")
                  : tMcp("cardNotConnected")}
            </CardStatus>
          )
        }
        selected={isOn}
        onOpen={disabled ? undefined : () => setSettingsOpen(true)}
      />
      <McpBindingDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        name={name}
        icon={icon}
        url={entry?.url ?? connection?.url ?? null}
        onEnabled={toggle}
        bindings={bindings}
        connections={connections}
        catalogKey={personalBindable ? entry.key : null}
        onChange={onRebind}
        onTools={(ref, probed, server) => {
          setSettingsOpen(false);
          onTools(ref, probed, server);
        }}
        onConnect={
          entry
            ? () => {
                setSettingsOpen(false);
                onConnect(entry);
              }
            : undefined
        }
        personalTools={personalTools}
        ownAccounts={ownAccounts}
        onDisconnectOwn={onDisconnectOwn}
        onSignInOwn={onSignInOwn}
        onConnectOwn={
          entry && onConnectOwn
            ? () => {
                setSettingsOpen(false);
                onConnectOwn(entry);
              }
            : undefined
        }
        onConfigure={
          configure
            ? (scope) => {
                setSettingsOpen(false);
                configure(scope);
              }
            : undefined
        }
        disabled={disabled}
      />
    </>
  );
}

/** Spec references this Builder cannot resolve - named, so they are not lost silently. */
function OrphanedIds({ ids }: { ids: string[] }) {
  const t = useTranslations("agents");
  if (ids.length === 0) return null;
  return (
    <p className="text-muted-foreground text-xs">
      {t("orphanedServers", { count: ids.length })}{" "}
      <span className="font-mono break-all">{ids.join(", ")}</span>
    </p>
  );
}
