"use client";

import { useMemo, useState } from "react";
import { Building2, ChevronDown, ExternalLink, Plug, Plus, User } from "lucide-react";
import { toast } from "sonner";

import {
  Badge,
  Button,
  Card,
  CardContent,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  ListCard,
  Pager,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useListControls,
} from "@/components/ui";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { McpConnectionDialog } from "@/components/mcp/mcp-connection-dialog";
import { McpToolPickerDialog } from "@/components/mcp/mcp-tool-picker-dialog";
import {
  SCOPE_LABEL,
  type ConnectionFormValues,
  type DraftState,
  type Scope,
  type ToolPickerState,
} from "@/components/mcp/mcp-server-list-types";
import { useMcpServers } from "@/hooks";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/api-error";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import { startMcpOAuth } from "@/lib/mcp-connections-api";
import {
  CUSTOM_CATEGORY,
  MCP_AUTH_LABEL,
  MCP_STATE_LABEL,
  connectionState,
} from "@/lib/mcp-servers";
import type { McpServerRow } from "@/lib/mcp-servers";
import { useTranslations } from "next-intl";

const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;

/** Whether a row is filtered by whether anybody has connected it. */
type StateFilter = "all" | "connected" | "not-connected";

/**
 * A backend category slug as a heading.
 *
 * The catalog's categories are identifiers - `project-management`,
 * `observability` - and uppercasing one in CSS turns the hyphen into a visible
 * seam that reads as a machine field rather than a section of a catalogue.
 */
function categoryLabel(category: string): string {
  return category.replace(/-/g, " ");
}

/** The row's sentence, from whichever side wrote it. */
function rowDescription(row: McpServerRow, t: (key: string) => string): string {
  if (row.descriptionKey !== null) return t(row.descriptionKey);
  return row.description ?? "";
}

interface McpServerListProps {
  /** False for a member without `connections:manage` - the organization column reads only. */
  canManageOrganization: boolean;
}

/**
 * Every MCP server, with connection state on the row rather than on a second page.
 *
 * The list is the catalog, because a catalog entry is not a sibling of a
 * connection - it is what a connection points at. Servers nobody curated appear
 * here too, so a credential is never reachable only from a URL somebody
 * remembers.
 *
 * Each row has two columns because there are genuinely two owners, and the
 * difference decides what the connection can be used for:
 *
 * - **Organization** - the organization's credential. The only kind an agent
 *   spec may bind, because a published agent must not reach different tools
 *   depending on whose session ran it. Gated on `connections:manage`.
 * - **You** - your own credential, used by your assistant in chat and by
 *   nothing else. Never offered to an agent.
 *
 * OAuth is offered on the personal column only. A consent grant is one human's,
 * and holding it as the organization's would give everybody that member's
 * access and lose it the day their account closed. There is no endpoint for it,
 * so the row says why rather than showing a button that cannot work.
 */
export function McpServerList({ canManageOrganization }: McpServerListProps) {
  const t = useTranslations("mcp");
  const tErrors = useTranslations("errors");
  const { rows, organization, personal, recordTools } = useMcpServers();
  const [category, setCategory] = useState<string>("all");
  const [state, setState] = useState<StateFilter>("all");

  // The catalog is compiled into the deployment and merged with the
  // organization's connections in the browser, so filtering it is a filter and
  // not a request. A round trip per keystroke over data already in hand would
  // be the slower design, not the more scalable one.
  const categories = useMemo(
    () => [...new Set(rows.map((row) => row.category).filter(Boolean))].sort(),
    [rows],
  );
  const narrowed = useMemo(
    () =>
      // Custom servers last: the catalog is the point of the grid, and what
      // somebody typed a URL for is the exception to it. Catalog order is
      // otherwise preserved by `mergeServers`.
      [...rows]
        .sort(
          (a, b) => Number(a.category === CUSTOM_CATEGORY) - Number(b.category === CUSTOM_CATEGORY),
        )
        .filter((row) => category === "all" || row.category === category)
        .filter((row) => {
          if (state === "all") return true;
          const connected = row.organization !== null || row.personal !== null;
          return state === "connected" ? connected : !connected;
        }),
    [rows, category, state],
  );
  const list = useListControls({
    items: narrowed,
    matches: (row, query) =>
      row.name.toLowerCase().includes(query) ||
      rowDescription(row, t).toLowerCase().includes(query) ||
      (row.url ?? "").toLowerCase().includes(query),
  });

  const [draft, setDraft] = useState<DraftState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toolPicker, setToolPicker] = useState<ToolPickerState | null>(null);
  // The connection a disconnect has been asked for and not yet granted, and
  // whether a granted one is still in flight. `confirmBusy` is what makes a
  // second click a no-op: `window.confirm` blocked the thread, so a double
  // DELETE was impossible; a `ConfirmDialog` does not, so the guard has to.
  const [disconnecting, setDisconnecting] = useState<{
    scope: Scope;
    connection: McpConnectionRecord;
  } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const api = (scope: Scope) => (scope === "organization" ? organization : personal);

  const openDraft = (scope: Scope, row: McpServerRow, existing: McpConnectionRecord | null) => {
    // The dialog seeds its own fields from this - name, url and auth type off
    // the row and any connection being edited.
    setDraft({ scope, row, existing });
  };

  /** Probe a server, returning its tools or null after saying why not. */
  const probe = async (scope: Scope, connection: McpConnectionRecord) => {
    setBusyId(connection.id);
    try {
      const result = await api(scope).test(connection.id);
      if (!result.ok) {
        toast.error(result.error ?? t("serverCouldNotBe"));
        return null;
      }
      recordTools(connection.id, result.tools);
      return result.tools;
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, t("checkFailed")));
      return null;
    } finally {
      setBusyId(null);
    }
  };

  const handleTools = async (scope: Scope, connection: McpConnectionRecord) => {
    const tools = await probe(scope, connection);
    if (!tools) return;
    setToolPicker({
      scope,
      connection,
      tools,
      checked: new Set(
        connection.allowed_tools === null
          ? tools.map((tool) => tool.name)
          : connection.allowed_tools,
      ),
    });
  };

  const handleOAuth = async (row: McpServerRow, name: string, scope: Scope = "personal") => {
    setBusyId(row.key);
    try {
      const { authorization_url } = await startMcpOAuth({ name, url: row.url ?? "" }, scope);
      window.location.href = authorization_url;
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, t("couldNotStartSign")));
      setBusyId(null);
    }
    // On success the browser navigates away - leave the row busy.
  };

  const handleSubmit = async (values: ConnectionFormValues) => {
    if (!draft) return;
    const name = values.name.trim().toLowerCase();
    const url = values.url.trim();
    // Only a token connection carries one. Switching to OAuth or None and
    // submitting must not quietly store whatever was typed before.
    const token = values.auth === "token" ? values.token.trim() : "";
    if (!NAME_PATTERN.test(name)) {
      toast.error(t("nameMustBeLowercase"));
      return;
    }
    if (!/^https?:\/\//.test(url)) {
      toast.error(t("urlMustStartWithHttp"));
      return;
    }
    const { row, existing } = draft;
    const scope = values.scope;

    // OAuth is not a row this dialog writes: the grant is obtained at the
    // provider's consent screen and the connection is created by the callback.
    // Sending the form would make an unauthorized bearer connection that then
    // has to be repaired.
    if (values.auth === "oauth" && existing === null) {
      setDraft(null);
      await handleOAuth({ ...row, url }, name, scope);
      return;
    }

    setSubmitting(true);
    try {
      if (existing === null) {
        const created = await api(scope).create({
          name,
          url,
          ...(token ? { auth_token: token } : {}),
          // Only the organization API records provenance; a personal connection
          // has no column for it and would 422 on an unexpected field.
          ...(scope === "organization" && row.entry ? { catalog_key: row.entry.key } : {}),
        });
        toast.success(
          scope === "organization"
            ? t("connectedForOrg", { name })
            : t("connectedForYou", { name }),
        );
        setDraft(null);
        void handleTools(scope, created);
      } else {
        // Only what changed. Re-sending the same URL discards the last check
        // result, and a stale green tick is how somebody publishes an agent
        // bound to a server nobody has reached.
        await api(scope).update(existing.id, {
          ...(name !== existing.name ? { name } : {}),
          ...(url !== existing.url ? { url } : {}),
          ...(token ? { auth_token: token } : values.clearToken ? { auth_token: "" } : {}),
        });
        toast.success(t("serverUpdated", { name }));
        setDraft(null);
      }
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, t("couldNotSaveServer")));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDisconnect = (scope: Scope, connection: McpConnectionRecord) => {
    setDisconnecting({ scope, connection });
  };

  const confirmDisconnect = async () => {
    if (!disconnecting) return;
    const { scope, connection } = disconnecting;
    setConfirmBusy(true);
    try {
      await api(scope).remove(connection.id);
      toast.success(t("serverDisconnected", { name: connection.name }));
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, t("couldNotDisconnect")));
    } finally {
      setConfirmBusy(false);
      setDisconnecting(null);
    }
  };

  const handleSaveTools = async () => {
    if (!toolPicker) return;
    const { scope, connection, tools, checked } = toolPicker;
    setSubmitting(true);
    try {
      if (checked.size === tools.length) {
        // Everything selected → store NULL, so tools the server adds later flow
        // through instead of silently staying off.
        await api(scope).update(connection.id, { clear_allowed_tools: true });
      } else {
        await api(scope).update(connection.id, { allowed_tools: [...checked] });
      }
      toast.success(t("toolSelectionSaved"));
      setToolPicker(null);
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, t("couldNotSaveTool")));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <ListCard
        data-tour="mcp-catalog"
        title={t("servers")}
        counted={t("serverCount", { count: rows.length })}
        controls={
          <SearchInput
            value={list.query}
            onChange={list.setQuery}
            placeholder={t("searchServers")}
          />
        }
        contentClassName="space-y-4 p-4"
      >
        <div data-tour="mcp-filter" className="flex flex-wrap items-center gap-2">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="w-auto min-w-40" aria-label={t("category")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("allCategories")}</SelectItem>
              {categories.map((entry) => (
                <SelectItem key={entry} value={entry}>
                  {categoryLabel(entry)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={state} onValueChange={(value) => setState(value as StateFilter)}>
            <SelectTrigger className="w-auto min-w-36" aria-label={t("connectionState")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("anyState")}</SelectItem>
              <SelectItem value="connected">{t("connected")}</SelectItem>
              <SelectItem value="not-connected">{t("notConnected")}</SelectItem>
            </SelectContent>
          </Select>
          <div className="flex-1" />
          {canManageOrganization && (
            <Button
              size="sm"
              variant="outline"
              data-tour="mcp-add"
              onClick={() =>
                openDraft(
                  "organization",
                  {
                    key: "new",
                    name: t("customServer"),
                    description: null,
                    descriptionKey: null,
                    category: CUSTOM_CATEGORY,
                    auth: "token",
                    url: null,
                    docsUrl: null,
                    tokenHint: null,
                    entry: null,
                    organization: null,
                    personal: null,
                  },
                  null,
                )
              }
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              {t("addCustomServer")}
            </Button>
          )}
        </div>

        {/*
         * One grid over the whole catalog, and no per-category sections.
         *
         * The categories were headings until it was a grid, and a grid made the
         * arithmetic obvious: this catalog has six entries under six distinct
         * categories, so every section held exactly one card and the page was a
         * column of headings down the left quarter of the screen. A category that
         * groups one thing is not a group - so it moves onto the card, where it
         * still says what the server is for without claiming to sort anything.
         *
         * Three columns at a normal window, four on a wide one. Six to a dozen
         * cards then land in two or three rows with no scrolling, which is the
         * only reason to lay a catalog out as a grid rather than as rows.
         */}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {list.visible.map((row, index) => (
            <Card
              key={row.key}
              role="group"
              aria-label={row.name}
              className="h-full"
              data-tour={index === 0 ? "mcp-connect" : undefined}
            >
              {/* No hover state, unlike the agents grid: there a card is a link and
                the border lighting up says so. Here the actions are inside the
                card, and a card that responds to a hover but does nothing when
                clicked is a worse lie than a flat one. */}
              <CardContent className="flex h-full flex-col gap-3 p-4">
                <div className="flex items-start gap-2.5">
                  <McpServerIcon
                    icon={row.entry?.icon ?? null}
                    name={row.name}
                    className="mt-0.5 h-6 w-6"
                  />
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-start justify-between gap-2">
                      <span className="truncate text-sm font-medium">{row.name}</span>
                      <Badge variant="outline" className="shrink-0">
                        {t(MCP_AUTH_LABEL[row.auth])}
                      </Badge>
                    </div>
                    <p className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
                      {row.category === CUSTOM_CATEGORY
                        ? t("notCatalog")
                        : categoryLabel(row.category)}
                    </p>
                    <p className="text-muted-foreground line-clamp-2 text-sm">
                      {rowDescription(row, t)}
                    </p>
                    {row.url === null ? (
                      // Prose, so it is set as prose. Monospacing this sentence
                      // and then truncating it produced "Self-hosted - you supply
                      // the…", which reads as a URL that got cut off.
                      <p className="text-muted-foreground text-xs">{t("selfHostedYouSupply")}</p>
                    ) : (
                      // Truncated rather than wrapped: spelled out, the URL is the
                      // tallest thing on the card, and the full editable copy is
                      // one click away in the dialog.
                      <p
                        className="text-muted-foreground truncate font-mono text-xs"
                        title={row.url}
                      >
                        {/* A query string may carry a key - never render one. */}
                        {`${row.url.split("?")[0]}${row.url.includes("?") ? "?…" : ""}`}
                      </p>
                    )}
                    {row.docsUrl && (
                      <a
                        href={row.docsUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline underline-offset-4"
                      >
                        {t("documentation")}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                </div>

                {/* Pushed to the foot, and the rule above it is why that reads as
                  a decision rather than a hole. An earlier version kept the
                  actions directly under the description to avoid a void in the
                  middle of the card - but cards in a row are the same height and
                  their descriptions are not, so the buttons landed at a
                  different height in every column. Consistent placement is worth
                  more than tight spacing: a separator turns the slack into an
                  action bar. */}
                <div className="mt-auto">
                  {/* One row, always, and always at the foot of the card.
                    The block above takes the slack, so a description that runs
                    to four lines and one that runs to two put their actions in
                    the same place - which is the whole reason a grid of cards
                    is scannable. State rides on the trigger rather than on a
                    chip of its own, because a chip on some cards and not others
                    is the misalignment again, one row up. */}
                  <div className="border-border mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
                    {(row.organization === null || row.personal === null) && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          openDraft(defaultScope(row, canManageOrganization), row, null)
                        }
                        disabled={busyId === row.key}
                      >
                        <Plug className="mr-1 h-3.5 w-3.5" />
                        {busyId === row.key ? t("redirecting") : t("connectAction")}
                      </Button>
                    )}
                    {row.organization && canManageOrganization && (
                      <ConnectionMenu
                        scope="organization"
                        row={row}
                        connection={row.organization}
                        busyId={busyId}
                        onEdit={(connection) => openDraft("organization", row, connection)}
                        onTools={(connection) => handleTools("organization", connection)}
                        onDisconnect={(connection) => handleDisconnect("organization", connection)}
                        onOAuth={() =>
                          handleOAuth(row, row.organization?.name ?? row.name, "organization")
                        }
                      />
                    )}
                    {row.organization && !canManageOrganization && (
                      <ScopeChip scope="organization" connection={row.organization} />
                    )}
                    {row.personal && (
                      <ConnectionMenu
                        scope="personal"
                        row={row}
                        connection={row.personal}
                        busyId={busyId}
                        onEdit={(connection) => openDraft("personal", row, connection)}
                        onTools={(connection) => handleTools("personal", connection)}
                        onDisconnect={(connection) => handleDisconnect("personal", connection)}
                        onOAuth={() => handleOAuth(row, row.personal?.name ?? row.name, "personal")}
                      />
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
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
      </ListCard>

      <McpConnectionDialog
        draft={draft}
        onClose={() => setDraft(null)}
        submitting={submitting}
        canManageOrganization={canManageOrganization}
        onSubmit={handleSubmit}
      />

      <McpToolPickerDialog
        toolPicker={toolPicker}
        setToolPicker={setToolPicker}
        submitting={submitting}
        onSave={handleSaveTools}
      />

      {disconnecting && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && !confirmBusy && setDisconnecting(null)}
          title={t("disconnectServerTitle")}
          description={
            disconnecting.scope === "organization"
              ? t("disconnectOrgWarning", { name: disconnecting.connection.name })
              : t("disconnectWarning", { name: disconnecting.connection.name })
          }
          confirmLabel={t("disconnect")}
          destructive
          loading={confirmBusy}
          onConfirm={confirmDisconnect}
        />
      )}
    </>
  );
}

/**
 * Where a server is held, and whether it works there.
 *
 * A chip per owner rather than a panel per owner. The card sits in a grid, and
 * the question somebody scanning a grid is asking is "is this connected, and
 * for whom" - two words, twice. Everything you can *do* about it hangs off one
 * button below, because the owner is a choice inside the flow rather than a
 * reason to draw the flow twice.
 */
function ScopeChip({
  scope,
  connection,
}: {
  scope: Scope;
  connection: McpConnectionRecord | null;
}) {
  const t = useTranslations("mcp");
  const state = connectionState(connection);
  const Icon = scope === "organization" ? Building2 : User;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs",
        state === "connected"
          ? "border-success/40 bg-success/10 text-foreground"
          : state === "error"
            ? "border-destructive/40 bg-destructive/10 text-foreground"
            : "border-border text-muted-foreground",
      )}
      title={`${t(SCOPE_LABEL[scope])}: ${t(MCP_STATE_LABEL[state])}`}
    >
      <Icon className="h-3 w-3 shrink-0" aria-hidden />
      {t(SCOPE_LABEL[scope])}
      <span aria-hidden>·</span>
      {t(MCP_STATE_LABEL[state])}
    </span>
  );
}

/**
 * Which owner the Connect button offers first.
 *
 * The one that has nothing yet, preferring the organization when both are
 * empty - a server connected for the organization is available to every agent,
 * which is what somebody adding one on this page is usually after.
 */
function defaultScope(row: McpServerRow, canManageOrganization: boolean): Scope {
  if (canManageOrganization && row.organization === null) return "organization";
  return "personal";
}

/**
 * Everything you can do to one existing connection, behind one control.
 *
 * A card in a grid has room for a primary action and no more. Laid out flat,
 * a server connected for one owner grew four buttons - and a server mid-OAuth
 * grew five, one of which read "you" beside a slider icon and meant "edit the
 * personal connection". The owner is what the trigger says; the verbs are
 * inside.
 */
function ConnectionMenu({
  scope,
  row,
  connection,
  busyId,
  onEdit,
  onTools,
  onDisconnect,
  onOAuth,
}: {
  scope: Scope;
  row: McpServerRow;
  connection: McpConnectionRecord;
  busyId: string | null;
  onEdit: (connection: McpConnectionRecord) => void;
  onTools: (connection: McpConnectionRecord) => void;
  onDisconnect: (connection: McpConnectionRecord) => void;
  onOAuth: () => void;
}) {
  const t = useTranslations("mcp");
  const state = connectionState(connection);
  const busy = busyId === connection.id || busyId === row.key;
  const owner = t(SCOPE_LABEL[scope]);
  const Icon = scope === "organization" ? Building2 : User;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          aria-label={t("manageNamed", { name: owner })}
          title={`${owner}: ${t(MCP_STATE_LABEL[state])}`}
        >
          <Icon className="mr-1 h-3.5 w-3.5" />
          {owner}
          {/* The state, as a dot on the control that acts on it. A separate chip
              put it on its own line, which made the action row sit lower on the
              cards that had one - the misalignment this layout exists to fix. */}
          <span
            aria-hidden
            className={cn(
              "ml-1.5 inline-block h-1.5 w-1.5 rounded-full",
              state === "connected"
                ? "bg-success"
                : state === "error"
                  ? "bg-destructive"
                  : "bg-muted-foreground/50",
            )}
          />
          <ChevronDown className="ml-1 h-3 w-3 opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {/* First, and only when it is the thing standing between this server and
            working: an unauthorized connection is the one state where every
            other verb here is premature. */}
        {state === "needs-authorization" && (
          <DropdownMenuItem onSelect={onOAuth}>{t("finishSign")}</DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => onTools(connection)}>
          {t("checkConnection")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onEdit(connection)}>{t("settings")}</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className="text-destructive focus:text-destructive"
          onSelect={() => onDisconnect(connection)}
        >
          {t("disconnect")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
