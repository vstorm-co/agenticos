"use client";

import { useState } from "react";
import { Check, Plug, UserRound, Wrench } from "lucide-react";

import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import {
  Badge,
  Button,
  Checkbox,
  Pager,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useListControls,
} from "@/components/ui";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import {
  connectionState,
  entryForConnection,
  MCP_AUTH_LABEL,
  MCP_STATE_LABEL,
} from "@/lib/mcp-servers";
import { cn } from "@/lib/utils";
import type { McpServerRef } from "@/types/agents";
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
 * A binding is one of two kinds, and the card asks which. **The organization's
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
  disabled,
}: McpServerPickerProps) {
  const t = useTranslations("agents");
  const tMcp = useTranslations("mcp");
  const [connectedOnly, setConnectedOnly] = useState(false);
  const known = new Set(connections.map((connection) => connection.id));
  const orphaned = value.flatMap((ref) =>
    ref.account === "organization" && !known.has(ref.connection_id) ? [ref.connection_id] : [],
  );

  /** Replace whatever this row's binding was with `next`, or drop it. */
  const rebind = (row: CardRow, next: McpServerRef | null) => {
    const ids = new Set(row.connections.map((connection) => connection.id));
    const others = value.filter(
      (ref) =>
        !(
          (ref.account === "organization" && ids.has(ref.connection_id)) ||
          (ref.account === "personal" && ref.catalog_key === row.entry?.key)
        ),
    );
    onChange(next === null ? others : [...others, next]);
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
        auth: tMcp(MCP_AUTH_LABEL[entry.auth]),
        entry,
        connections: owned,
      };
    }),
    ...custom.map((connection): CardRow => ({
      key: connection.id,
      name: connection.name,
      description: connection.url,
      icon: null,
      auth: null,
      entry: null,
      connections: [connection],
    })),
  ];

  const narrowed = connectedOnly ? rows.filter((row) => row.connections.length > 0) : rows;
  const list = useListControls({
    items: narrowed,
    matches: (row, query) =>
      row.name.toLowerCase().includes(query) || row.description.toLowerCase().includes(query),
  });

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

      <div className="grid gap-2 sm:grid-cols-2">
        {list.visible.map((row) => (
          <ServerCard
            key={row.key}
            row={row}
            binding={bindingFor(row, value)}
            onRebind={(next) => rebind(row, next)}
            onTools={onTools}
            onConnect={onConnect}
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
  auth: string | null;
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

/** The spec's binding for this row, of either kind, or none. */
function bindingFor(row: CardRow, value: McpServerRef[]): McpServerRef | null {
  const ids = new Set(row.connections.map((connection) => connection.id));
  return (
    value.find(
      (ref) =>
        (ref.account === "organization" && ids.has(ref.connection_id)) ||
        (ref.account === "personal" && row.entry !== null && ref.catalog_key === row.entry.key),
    ) ?? null
  );
}

function ServerCard({
  row,
  binding,
  onRebind,
  onTools,
  onConnect,
  disabled,
}: {
  row: CardRow;
  binding: McpServerRef | null;
  onRebind: (next: McpServerRef | null) => void;
  onTools: (ref: McpServerRef, probed: OrgMcpConnectionRecord, name: string) => void;
  onConnect: (entry: McpCatalogEntry) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  // The state words belong to the MCP page, which is where they are also read.
  const tMcp = useTranslations("mcp");
  const { name, description, icon, auth, connections, entry } = row;
  // Which of the organization's accounts this row acts on: the one the spec
  // names, else the first. Ticking the row binds it; the select changes which.
  const connection =
    connections.find(
      (account) => binding?.account === "organization" && account.id === binding.connection_id,
    ) ??
    connections[0] ??
    null;
  const state = connectionState(connection);
  const isOn = binding !== null;
  const personal = binding?.account === "personal";
  const orgBindable = connection !== null;
  // A server the catalog does not describe has no key for a person's own
  // connection to be matched on, so only an organization's can be bound.
  const personalBindable = entry !== null;

  const bindOrganization = (target: OrgMcpConnectionRecord) =>
    onRebind({
      account: "organization",
      connection_id: target.id,
      // Carried over: the tools are chosen for the *agent*, and the account it
      // speaks through is a different question - the server offers the same
      // tools either way.
      allowed_tools: binding?.allowed_tools ?? null,
    });
  const bindPersonal = () =>
    entry &&
    onRebind({
      account: "personal",
      catalog_key: entry.key,
      allowed_tools: binding?.allowed_tools ?? null,
    });

  const body = (
    <>
      <span
        className={cn(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
          isOn ? "border-brand bg-brand text-brand-foreground" : "border-input",
          !orgBindable && "border-dashed",
        )}
      >
        {isOn && <Check className="h-3 w-3" />}
      </span>
      {/* Beside the name rather than at the edge: the mark is what the eye
          lands on when scanning fifty rows, and it belongs to the server, not
          to the checkbox. */}
      <McpServerIcon icon={icon} name={name} className="mt-0.5" />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{name}</span>
          {auth && <Badge variant="outline">{auth}</Badge>}
          {personal ? (
            <Badge variant="secondary">{t("eachPersonsOwnAccount")}</Badge>
          ) : (
            state !== "connected" && (
              <Badge variant={state === "error" ? "destructive" : "secondary"}>
                {tMcp(MCP_STATE_LABEL[state])}
              </Badge>
            )
          )}
        </span>
        <span className="text-muted-foreground mt-1 block truncate text-xs">{description}</span>
      </span>
    </>
  );

  // No organization account to bind and none bound, so the card is the way to
  // make one rather than a checkbox that would have no id to write into the
  // spec - it opens the connect dialog here rather than linking to the servers
  // page, which threw away an unsaved draft. Beside it, the other kind of
  // binding, which needs no connection to exist: each person brings their own.
  if (!orgBindable && !isOn) {
    return (
      <div className="border-border flex flex-col gap-2 rounded-xl border border-dashed p-4">
        <button
          type="button"
          disabled={disabled || entry === null}
          onClick={() => entry && onConnect(entry)}
          className="hover:text-foreground flex items-start gap-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60"
        >
          {body}
          <Plug className="text-muted-foreground mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="sr-only">{t("connectServerFirst")}</span>
        </button>
        {personalBindable && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={disabled}
            onClick={bindPersonal}
            className="self-start pl-7"
          >
            <UserRound className="mr-1 h-3.5 w-3.5" />
            {t("useEachPersonsOwnAccount")}
          </Button>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "rounded-xl border p-4 transition-colors",
        isOn ? "border-brand bg-brand/5" : "hover:border-foreground/20",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <button
        type="button"
        role="checkbox"
        aria-checked={isOn}
        aria-label={name}
        disabled={disabled}
        onClick={() => (isOn ? onRebind(null) : connection && bindOrganization(connection))}
        className="flex w-full items-start gap-3 text-left"
      >
        {body}
      </button>

      {/* Whose account, once bound. The organization's is what a binding
          means by default; each person's own is the other kind, and switching
          rewrites the binding rather than flagging it - the spec stores which
          kind it is, and a run reads that. */}
      {isOn && personalBindable && (
        <div className="mt-3 pl-7">
          <Select
            value={personal ? "personal" : "organization"}
            disabled={disabled}
            onValueChange={(next) =>
              next === "personal" ? bindPersonal() : connection && bindOrganization(connection)
            }
          >
            <SelectTrigger className="h-8 text-xs" aria-label={t("accountForServer", { name })}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {/* Offered only where there is one to bind; the row above says
                  how to connect one. */}
              {orgBindable && (
                <SelectItem value="organization" className="text-xs">
                  {t("organizationsAccount")}
                </SelectItem>
              )}
              <SelectItem value="personal" className="text-xs">
                {t("eachPersonsOwnAccount")}
              </SelectItem>
            </SelectContent>
          </Select>
          {personal && (
            <p className="text-muted-foreground mt-2 text-xs">{t("eachPersonsOwnAccountHint")}</p>
          )}
        </div>
      )}

      {/* Which connection, where the organization holds more than one. Choosing
          is binding: there is nowhere but the spec to remember a choice, so a
          select that only recorded an intention would forget it on reload. */}
      {!personal && connections.length > 1 && connection && (
        <div className="mt-3 pl-7">
          <Select
            value={connection.id}
            disabled={disabled}
            onValueChange={(next) => {
              const target = connections.find((option) => option.id === next);
              if (target) bindOrganization(target);
            }}
          >
            <SelectTrigger className="h-8 text-xs" aria-label={t("whichAccount", { name })}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {connections.map((option) => (
                <SelectItem key={option.id} value={option.id} className="text-xs">
                  {/* The label if somebody set one, and the slug beside it
                      either way - that is the prefix the model reads, and a
                      run's tool calls are recorded under it. */}
                  {option.label ?? option.name}
                  {option.label !== null && (
                    <span className="text-muted-foreground ml-2 font-mono">{option.name}</span>
                  )}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Which of the server's tools this agent may call. The catalogue of
          tools comes from an organization connection's probe, so a binding to
          each person's own account can be narrowed only where the organization
          holds a connection to the same server - the server's tools are the
          same whoever's credential reaches them. */}
      {isOn && binding && connection && (
        <div className="mt-3 pl-7">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => onTools(binding, connection, name)}
          >
            <Wrench className="mr-1 h-3.5 w-3.5" />
            {binding.allowed_tools === null
              ? t("everyToolThisServerOffers")
              : t("toolCount", { count: binding.allowed_tools.length })}
          </Button>
        </div>
      )}
    </div>
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
