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
import type { McpServerRef } from "@/types/agents";
import type { McpCatalogEntry } from "@/types/mcp";
import { useTranslations } from "next-intl";

interface McpServerPickerProps {
  /** The organization's servers - the only ones an agent may be bound to. */
  connections: OrgMcpConnectionRecord[];
  /** The organization catalog: every server that can be connected in one click. */
  catalog: McpCatalogEntry[];
  /** `spec.mcp_servers`. */
  value: McpServerRef[];
  /**
   * The whole list, rebuilt.
   *
   * One callback rather than one per gesture. Binding, choosing which account
   * and turning personal substitution on all write the same list, and three
   * callbacks reading the same spec would each start from the copy the previous
   * one replaced.
   */
  onChange: (next: McpServerRef[]) => void;
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
 * stores connection ids, and the only MCP things in this system with an id
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
 * a binding has nowhere to put a per-agent override. Separately, the approval capability gates only tools a
 * capability owns - MCP tools are not among them, so nothing here can be held
 * for a human.
 */
export function McpServerPicker({
  connections,
  catalog,
  value,
  onChange,
  onConnect,
  disabled,
}: McpServerPickerProps) {
  const t = useTranslations("agents");
  const tMcp = useTranslations("mcp");
  const [connectedOnly, setConnectedOnly] = useState(false);
  const bound = new Map(value.map((ref) => [ref.connection_id, ref]));
  const known = new Set(connections.map((connection) => connection.id));
  const orphaned = value.map((ref) => ref.connection_id).filter((id) => !known.has(id));

  /** Bind a connection, or drop it. */
  const toggle = (connectionId: string) =>
    onChange(
      bound.has(connectionId)
        ? value.filter((ref) => ref.connection_id !== connectionId)
        : [...value, { connection_id: connectionId, use_personal_when_available: false }],
    );

  /**
   * Point a bound row at a different account of the same server, keeping what
   * the binding already said. Binding when none of them was bound: there is
   * nowhere but the spec to remember a choice, so a select that only recorded
   * an intention would forget it on reload.
   */
  const choose = (options: OrgMcpConnectionRecord[], connectionId: string) => {
    const previous = options.find((option) => bound.has(option.id));
    const ids = new Set(options.map((option) => option.id));
    onChange([
      ...value.filter((ref) => !ids.has(ref.connection_id)),
      {
        connection_id: connectionId,
        use_personal_when_available: previous
          ? (bound.get(previous.id)?.use_personal_when_available ?? false)
          : false,
      },
    ]);
  };

  const setPersonal = (connectionId: string, use_personal_when_available: boolean) =>
    onChange(
      value.map((ref) =>
        ref.connection_id === connectionId ? { ...ref, use_personal_when_available } : ref,
      ),
    );

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
            binding={(id) => bound.get(id) ?? null}
            onToggle={toggle}
            onChoose={choose}
            onPersonal={setPersonal}
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
  binding,
  onToggle,
  onChoose,
  onPersonal,
  onConnect,
  disabled,
}: {
  name: string;
  description: string;
  icon?: string | null;
  auth: string | null;
  connections: OrgMcpConnectionRecord[];
  entry: McpCatalogEntry | null;
  binding: (connectionId: string) => McpServerRef | null;
  onToggle: (connectionId: string) => void;
  onChoose: (options: OrgMcpConnectionRecord[], connectionId: string) => void;
  onPersonal: (connectionId: string, use: boolean) => void;
  onConnect: (entry: McpCatalogEntry) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  // The state words belong to the MCP page, which is where they are also read.
  const tMcp = useTranslations("mcp");
  // Which account this row acts on: the one the spec already names, else the
  // first. Ticking the row binds it; the select below changes which it is.
  const ref = connections.map((account) => binding(account.id)).find((one) => one !== null) ?? null;
  const connection =
    connections.find((account) => account.id === ref?.connection_id) ?? connections[0] ?? null;
  const state = connectionState(connection);
  const isOn = ref !== null;
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

      {/* Only once bound: an agent that reaches this server through nobody has
          no account to substitute, and a switch that writes nothing is a
          promise the run will not keep. On the connection's own `catalog_key`
          rather than on the entry it renders under, because that is the column
          publish checks - `entryForConnection` also matches on URL, so a card
          can carry an entry while the row has no key to join a member's own
          connection to. */}
      {isOn && connection.catalog_key !== null && (
        <label className="mt-3 flex items-start gap-2 pl-7">
          <Checkbox
            checked={ref.use_personal_when_available}
            disabled={disabled}
            onCheckedChange={(next) => onPersonal(connection.id, next === true)}
            className="mt-0.5"
          />
          <span className="text-muted-foreground text-xs">
            {t("useTheirOwnAccount")}
            <span className="mt-0.5 block">{t("useTheirOwnAccountHint")}</span>
          </span>
        </label>
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
