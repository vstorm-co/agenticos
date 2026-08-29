"use client";

import { useState } from "react";
import { Check, Plug } from "lucide-react";

import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import {
  Badge,
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
import type { McpCatalogEntry } from "@/types/mcp";
import { useTranslations } from "next-intl";

interface McpServerPickerProps {
  /** The organization's servers - the only ones an agent may be bound to. */
  connections: OrgMcpConnectionRecord[];
  /** The organization catalog: every server that can be connected in one click. */
  catalog: McpCatalogEntry[];
  /** `spec.mcp_server_ids`. */
  selectedIds: string[];
  onToggle: (connectionId: string) => void;
  /**
   * Bind one of a server's accounts, replacing whichever of them is bound now.
   *
   * One call rather than an untoggle and a toggle: both would read the same
   * spec and the second would overwrite the first.
   */
  onChoose: (options: OrgMcpConnectionRecord[], connectionId: string) => void;
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
 * Only a connection can be bound, and that is not a UI preference. The spec
 * stores `mcp_server_ids`, and the only MCP things in this system with an id
 * are connections; a catalog entry is keyed by name and has none. So an
 * unconnected server is shown, described, and offers the way to connect it -
 * it is not a checkbox that would have nothing to write.
 *
 * It offers the **organization's** connections and never the caller's own.
 * `validate_spec` refuses a personal connection at publish, so offering one
 * here would be offering a choice that guarantees publishing fails. The reason
 * behind the refusal is the same one that decides what belongs on this screen:
 * an agent everybody runs cannot reach whatever the person who happened to
 * trigger it had connected.
 *
 * Ids in the spec that match no connection are shown rather than dropped: they
 * belong to a server that has since been removed, or to another organization in
 * an imported spec, and an id that quietly vanishes from a form is an id that
 * quietly vanishes from the spec.
 *
 * **What this picker cannot do, and says so.** The choice is per server, not per
 * tool, and it is not an approval decision. `allowed_tools` lives on the
 * connection, so two agents bound to the same server get the same tools, and
 * `AgentSpec.mcp_server_ids` is a flat list of ids with nowhere to put a
 * per-agent override. Separately, the approval capability gates only tools a
 * capability owns - MCP tools are not among them, so nothing here can be held
 * for a human.
 */
export function McpServerPicker({
  connections,
  catalog,
  selectedIds,
  onToggle,
  onChoose,
  onConnect,
  disabled,
}: McpServerPickerProps) {
  const t = useTranslations("agents");
  const tMcp = useTranslations("mcp");
  const [connectedOnly, setConnectedOnly] = useState(false);
  const chosen = new Set(selectedIds);
  const known = new Set(connections.map((connection) => connection.id));
  const orphaned = selectedIds.filter((id) => !known.has(id));

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
      const bound = described.get(entry.key) ?? [];
      return {
        key: entry.key,
        name: entry.name,
        description: entry.description,
        icon: entry.icon,
        auth: tMcp(MCP_AUTH_LABEL[entry.auth]),
        entry,
        connections: bound,
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
        {/* The catalog is mostly servers nobody has connected, and only a
            connected one can be bound - so "hide the rest" is the filter this
            picker actually needs. */}
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
            name={row.name}
            description={row.description}
            icon={row.icon}
            auth={row.auth}
            connections={row.connections}
            entry={row.entry}
            selected={(id) => chosen.has(id)}
            onToggle={onToggle}
            onChoose={onChoose}
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
   * Empty means nothing to bind - the card offers to connect one instead. More
   * than one means the card asks *which*, because an agent binds a connection
   * and the answer to "whose credential is this" has to be on screen.
   */
  connections: OrgMcpConnectionRecord[];
  /** The catalog entry behind the row, so an unconnected one can be connected. */
  entry: McpCatalogEntry | null;
}

function ServerCard({
  name,
  description,
  icon,
  auth,
  connections,
  entry,
  selected,
  onToggle,
  onChoose,
  onConnect,
  disabled,
}: {
  name: string;
  description: string;
  icon?: string | null;
  auth: string | null;
  connections: OrgMcpConnectionRecord[];
  entry: McpCatalogEntry | null;
  selected: (connectionId: string) => boolean;
  onToggle: (connectionId: string) => void;
  onChoose: (options: OrgMcpConnectionRecord[], connectionId: string) => void;
  onConnect: (entry: McpCatalogEntry) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  // The state words belong to the MCP page, which is where they are also read.
  const tMcp = useTranslations("mcp");
  // Which account this row acts on: the one the spec already names, else the
  // first. Ticking the row binds it; the select below changes which it is.
  const bound = connections.find((account) => selected(account.id)) ?? null;
  const connection = bound ?? connections[0] ?? null;
  const state = connectionState(connection);
  const isOn = bound !== null;
  const bindable = connection !== null;

  const body = (
    <>
      <span
        className={cn(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
          isOn ? "border-brand bg-brand text-brand-foreground" : "border-input",
          !bindable && "border-dashed",
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
          {state !== "connected" && (
            <Badge variant={state === "error" ? "destructive" : "secondary"}>
              {tMcp(MCP_STATE_LABEL[state])}
            </Badge>
          )}
        </span>
        <span className="text-muted-foreground mt-1 block truncate text-xs">{description}</span>
      </span>
    </>
  );

  // Nothing to bind to, so the card is the way to make one rather than a
  // checkbox that would have no id to write into the spec. It opens the connect
  // dialog here rather than linking to the servers page, which threw away an
  // unsaved draft and asked somebody to find their way back.
  if (!bindable) {
    return (
      <button
        type="button"
        disabled={disabled || entry === null}
        onClick={() => entry && onConnect(entry)}
        className="border-border hover:border-foreground/20 flex items-start gap-3 rounded-xl border border-dashed p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60"
      >
        {body}
        <Plug className="text-muted-foreground mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="sr-only">{t("connectServerFirst")}</span>
      </button>
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
        onClick={() => onToggle(connection.id)}
        className="flex w-full items-start gap-3 text-left"
      >
        {body}
      </button>

      {/* Which account, where the organization holds more than one. Choosing is
          binding: there is nowhere but the spec to remember a choice, so a
          select that only recorded an intention would forget it on reload. */}
      {connections.length > 1 && (
        <div className="mt-3 pl-7">
          <Select
            value={connection.id}
            disabled={disabled}
            onValueChange={(next) => onChoose(connections, next)}
          >
            <SelectTrigger className="h-8 text-xs" aria-label={t("whichAccount", { name })}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {connections.map((option) => (
                <SelectItem key={option.id} value={option.id} className="font-mono text-xs">
                  {option.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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
