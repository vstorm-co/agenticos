"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronRight, ExternalLink, Plug, Plus } from "lucide-react";
import { toast } from "sonner";

import {
  Badge,
  Button,
  Card,
  CardContent,
  ConfirmDialog,
  ListCard,
  Pager,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { McpConnectionDialog } from "@/components/mcp/mcp-connection-dialog";
import { ServerConnectionsDialog } from "@/components/mcp/server-connections-dialog";
import { McpToolPickerDialog } from "@/components/mcp/mcp-tool-picker-dialog";
import {
  type ConnectionFormValues,
  type DraftState,
  type Scope,
  type ToolPickerState,
} from "@/components/mcp/mcp-server-list-types";
import { useMcpServers } from "@/hooks";
import { MCP_PAGE_SIZE, useMcpCatalog, useMcpCatalogPage } from "@/hooks/use-mcp-servers";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/api-error";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import { startMcpOAuth } from "@/lib/mcp-connections-api";
import {
  connectionState,
  CUSTOM_CATEGORY,
  matchingCustomRows,
  customRows,
  isReviewed,
  MCP_AUTH_LABEL,
  MCP_STATE_LABEL,
  rowsForEntries,
} from "@/lib/mcp-servers";
import type { McpServerRow } from "@/lib/mcp-servers";
import { useTranslations } from "next-intl";

const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;

/**
 * `?connect=<catalog key>` opens the personal connect flow for that server.
 *
 * The link an agent hands somebody when a binding to each person's own account
 * finds they have none: the backend writes it (`_personal_gap_briefing`), so the
 * parameter's name is a contract between the two rather than this file's own.
 */
const CONNECT_PARAM = "connect";

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

/**
 * A name nothing in this scope holds yet, for a second account on one server.
 *
 * The entry's own key first, because that is the ordinary case and reads
 * best; then `-2`, `-3` and so on. A name is unique per organization and
 * becomes the tool prefix, so seeding one already taken made the form's first
 * submit a guaranteed conflict.
 */
function freeName(row: McpServerRow, taken: Set<string>): string | undefined {
  const base = row.entry?.key;
  if (base === undefined) return undefined;
  if (!taken.has(base)) return base;
  for (let n = 2; ; n += 1) {
    const candidate = `${base}-${n}`;
    if (!taken.has(candidate)) return candidate;
  }
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
 *   spec may name by id, because a published agent must not reach different
 *   tools depending on whose session built it. Gated on `connections:manage`.
 * - **You** - your own credential. What an agent bound to *each person's own
 *   account* speaks through when you are the one talking to it, and what a
 *   `?connect=<key>` arrival from such an agent creates.
 *
 * OAuth is offered on the personal column only. A consent grant is one human's,
 * and holding it as the organization's would give everybody that member's
 * access and lose it the day their account closed. There is no endpoint for it,
 * so the row says why rather than showing a button that cannot work.
 */
export function McpServerList({ canManageOrganization }: McpServerListProps) {
  const t = useTranslations("mcp");
  const tErrors = useTranslations("errors");
  const { organization, personal, recordTools } = useMcpServers();
  // The whole curated catalog, for the category filter alone - see below.
  const catalog = useMcpCatalog();
  const [category, setCategory] = useState<string>("all");
  const [state, setState] = useState<StateFilter>("all");
  // The query, the category and the page all go to the server, because the list
  // is a request now rather than a filter over what the client holds. It held
  // the curated hundred and filtered them locally, which was right until 5,703
  // mirrored registry servers arrived behind them: filtering a page is filtering
  // whatever that page happened to contain, and so is ranking one.
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const listing = useMcpCatalogPage(query, category === "all" ? "" : category, page);

  // The page's catalog entries with their connections folded on. Custom rows are
  // *not* built from a page: whether a connection is "not in the catalog" is a
  // question about every entry, so asking it of fifty answers "yes" for a
  // connection whose entry is on another page - which put the Notion connection
  // at the foot of every page as an uncatalogued server, five times over, until
  // searching "notion" brought its entry onto the page and it merged again.
  const pageRows = useMemo(
    () => rowsForEntries(listing.servers, organization.connections, personal.connections),
    [listing.servers, organization.connections, personal.connections],
  );

  // Asked of the whole catalog, and appended once - on the last page, after
  // everything the catalog and the mirror hold, because that is where "and these
  // are yours" belongs in a list of five thousand.
  const customs = useMemo(
    () =>
      matchingCustomRows(
        customRows(catalog.servers, organization.connections, personal.connections),
        query,
        category === "all" ? "" : category,
      ),
    [catalog.servers, organization.connections, personal.connections, query, category],
  );

  const pageCount = Math.max(1, Math.ceil((listing.total + customs.length) / MCP_PAGE_SIZE));
  const onLastPage = page >= pageCount - 1;
  const rows = useMemo(
    () => (onLastPage ? [...pageRows, ...customs] : pageRows),
    [onLastPage, pageRows, customs],
  );

  // Answered by the server rather than derived from the rows on screen: a page
  // holds whichever categories landed on it, so a filter built from one offers a
  // different set on page two.
  const categories = useMemo(
    () => [...new Set(catalog.servers.map((entry) => entry.category).filter(Boolean))].sort(),
    [catalog.servers],
  );

  // The one filter still applied in the browser, and the only one that can be:
  // whether anybody has connected a server is a fact the client holds and the
  // server would have to be told. It narrows the page rather than the list, which
  // is the honest limit of doing it here.
  const visible = useMemo(
    () =>
      rows.filter((row) => {
        if (state === "all") return true;
        const connected = row.organizations.length > 0 || row.personals.length > 0;
        return state === "connected" ? connected : !connected;
      }),
    [rows, state],
  );

  function ask(next: string) {
    setQuery(next);
    setPage(0);
  }

  function narrow(next: string) {
    setCategory(next);
    setPage(0);
  }

  const [draft, setDraft] = useState<DraftState | null>(null);
  const [managing, setManaging] = useState<McpServerRow | null>(null);
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
    setDraft({
      scope,
      row,
      existing,
      suggestedName: existing ? undefined : freeName(row, takenNames(scope)),
    });
  };

  /** The names this scope already holds, which a new connection cannot take. */
  const takenNames = (scope: Scope): Set<string> =>
    new Set(
      (scope === "organization" ? organization.connections : personal.connections).map(
        (connection) => connection.name,
      ),
    );

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
      name: connection.name,
      connection,
      tools,
      checked: new Set(
        connection.allowed_tools === null
          ? tools.map((tool) => tool.name)
          : connection.allowed_tools,
      ),
      appliesTo: "connection",
    });
  };

  const handleOAuth = async (row: McpServerRow, name: string, scope: Scope = "personal") => {
    setBusyId(row.key);
    try {
      const { authorization_url } = await startMcpOAuth({ name, url: row.url ?? "" }, scope);
      // `assign`, not a write to `href`: the React compiler reads a property
      // write on `window` as mutating a value from outside the component.
      window.location.assign(authorization_url);
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, t("couldNotStartSign")));
      setBusyId(null);
    }
    // On success the browser navigates away - leave the row busy.
  };

  // The key `?connect=` arrived with, read once. Lazily, so the server render -
  // which has no window - and the client's first render agree on a closed
  // dialog; the row it names is derived below rather than set from an effect.
  const [connectKey, setConnectKey] = useState<string | null>(() =>
    typeof window === "undefined"
      ? null
      : new URL(window.location.href).searchParams.get(CONNECT_PARAM),
  );
  const catalogLoaded = catalog.servers.length > 0;
  const requestedRow = useMemo(
    () =>
      connectKey === null || !catalogLoaded
        ? null
        : (rowsForEntries(catalog.servers, organization.connections, personal.connections).find(
            (row) => row.entry?.key === connectKey,
          ) ?? null),
    [connectKey, catalogLoaded, catalog.servers, organization.connections, personal.connections],
  );
  // A token or credential-free server opens the personal connect dialog as
  // soon as the catalog has named the row - derived, so nothing has to be set.
  // Closing it is what clears the request.
  const requestedDraft: DraftState | null =
    draft === null && requestedRow !== null && requestedRow.auth !== "oauth"
      ? {
          scope: "personal",
          row: requestedRow,
          existing: null,
          suggestedName: freeName(requestedRow, takenNames("personal")),
        }
      : null;
  const activeDraft = draft ?? requestedDraft;
  const closeDraft = () => {
    setDraft(null);
    setConnectKey(null);
  };

  // The two halves that are not a render: the parameter is stripped as it is
  // read, like the OAuth outcome, so a reload does not reopen a dialog somebody
  // closed - and OAuth is a navigation, which no render can express. Guarded on
  // the parameter still being in the URL, so a refetch of the connections does
  // not send the browser to the consent screen a second time.
  useEffect(() => {
    if (connectKey === null || !catalogLoaded) return;
    const url = new URL(window.location.href);
    if (!url.searchParams.has(CONNECT_PARAM)) return;
    url.searchParams.delete(CONNECT_PARAM);
    window.history.replaceState({}, "", url.toString());
    if (requestedRow === null) {
      toast.error(t("noSuchServerToConnect", { key: connectKey }));
      return;
    }
    if (requestedRow.auth !== "oauth") return;
    const taken = new Set(personal.connections.map((connection) => connection.name));
    const name = freeName(requestedRow, taken) ?? connectKey;
    startMcpOAuth({ name, url: requestedRow.url ?? "" }, "personal")
      .then(({ authorization_url }) => window.location.assign(authorization_url))
      .catch((caught: unknown) =>
        toast.error(getErrorMessage(caught, tErrors, t("couldNotStartSign"))),
      );
  }, [connectKey, catalogLoaded, requestedRow, personal.connections, t, tErrors]);

  const handleSubmit = async (values: ConnectionFormValues) => {
    if (!activeDraft) return;
    const name = values.name.trim().toLowerCase();
    const label = values.label.trim();
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
    const { row, existing } = activeDraft;
    const scope = values.scope;

    // OAuth is not a row this dialog writes: the grant is obtained at the
    // provider's consent screen and the connection is created by the callback.
    // Sending the form would make an unauthorized bearer connection that then
    // has to be repaired.
    if (values.auth === "oauth" && existing === null) {
      closeDraft();
      await handleOAuth({ ...row, url }, name, scope);
      return;
    }

    setSubmitting(true);
    try {
      if (existing === null) {
        const created = await api(scope).create({
          name,
          url,
          ...(label ? { label } : {}),
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
        closeDraft();
        void handleTools(scope, created);
      } else {
        // Only what changed. Re-sending the same URL discards the last check
        // result, and a stale green tick is how somebody publishes an agent
        // bound to a server nobody has reached.
        await api(scope).update(existing.id, {
          ...(name !== existing.name ? { name } : {}),
          // `""` is what clears one, so an emptied field has to be sent rather
          // than treated as "nothing to say".
          ...(label !== (existing.label ?? "") ? { label } : {}),
          ...(url !== existing.url ? { url } : {}),
          ...(token ? { auth_token: token } : values.clearToken ? { auth_token: "" } : {}),
        });
        toast.success(t("serverUpdated", { name }));
        closeDraft();
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

  const handleNominate = async (connection: McpConnectionRecord, use: boolean) => {
    setBusyId(connection.id);
    try {
      await api("personal").update(connection.id, { is_default: use });
      toast.success(use ? t("agentsSpeakAsThis") : t("agentsNoLongerSpeak"));
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors));
    } finally {
      setBusyId(null);
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
        counted={t("serverCount", { count: listing.total + customs.length })}
        controls={<SearchInput value={query} onChange={ask} placeholder={t("searchServers")} />}
        contentClassName="space-y-4 p-4"
      >
        <div data-tour="mcp-filter" className="flex flex-wrap items-center gap-2">
          <Select value={category} onValueChange={narrow}>
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
                    organizations: [],
                    personals: [],
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
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {visible.map((row, index) => (
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
                      {/* One list holds both kinds, so the difference has to be
                          on the row rather than in a heading over half of it.
                          Nobody here checked a registry server: the description
                          is the publisher's and there is no token hint, which is
                          worth knowing before pasting a credential into it. */}
                      {isReviewed(row) ? (
                        <Badge variant="outline" className="shrink-0">
                          {t(MCP_AUTH_LABEL[row.auth])}
                        </Badge>
                      ) : (
                        <Badge
                          variant="secondary"
                          className="shrink-0"
                          title={t("fromRegistryHint")}
                        >
                          {t("fromRegistry")}
                        </Badge>
                      )}
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
                  {/* `min-w-0` so the row can shrink rather than overflow. Every
                      `Button` is `whitespace-nowrap` and nothing here could give
                      way, so the two controls took the full width, `ml-auto`
                      collapsed to nothing, and the `shrink-0` dot was pushed
                      past the card's right edge - visibly outside it on a card
                      with three connections. */}
                  <div className="border-border mt-3 flex min-w-0 items-center gap-1.5 border-t pt-3">
                    {/* Exactly two controls, whatever the card holds. The row
                        used to grow one chip per connection, so a server with
                        three accounts stood taller than its neighbours and the
                        grid went ragged - the misalignment this footer exists
                        to prevent, reintroduced one row down. */}
                    <Button
                      size="sm"
                      variant="outline"
                      className="shrink-0"
                      onClick={() => openDraft(defaultScope(row, canManageOrganization), row, null)}
                      disabled={busyId === row.key}
                    >
                      <Plug className="mr-1 h-3.5 w-3.5" />
                      {busyId === row.key ? t("redirecting") : t("connectAction")}
                    </Button>
                    {connectionCount(row) > 0 && (
                      <Button
                        size="sm"
                        variant="ghost"
                        // The one control allowed to give way: the count is the
                        // least important thing on the row, and something has to
                        // shrink or the dot leaves the card.
                        className="min-w-0"
                        onClick={() => setManaging(row)}
                        aria-label={t("manageConnectionsOn", { name: row.name })}
                      >
                        <span className="truncate">
                          {t("connectionCount", { count: connectionCount(row) })}
                        </span>
                        <ChevronRight className="ml-1 h-3.5 w-3.5" />
                      </Button>
                    )}
                    <StateDot row={row} />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <Pager
          page={page}
          pageCount={pageCount}
          matched={listing.total + customs.length}
          total={listing.total + customs.length}
          onPage={setPage}
          counted={t("serverCount", { count: listing.total + customs.length })}
        />
      </ListCard>

      <ServerConnectionsDialog
        row={managing}
        canManageOrganization={canManageOrganization}
        busyId={busyId}
        onClose={() => setManaging(null)}
        onConnect={(scope, row) => {
          setManaging(null);
          openDraft(scope, row, null);
        }}
        onEdit={(scope, row, connection) => {
          setManaging(null);
          openDraft(scope, row, connection);
        }}
        onTools={handleTools}
        onDisconnect={handleDisconnect}
        onNominate={handleNominate}
        onOAuth={(scope, row, connection) => handleOAuth(row, connection.name, scope)}
      />

      <McpConnectionDialog
        draft={activeDraft}
        onClose={closeDraft}
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
 * Which owner the Connect button offers first.
 *
 * The one that has nothing yet, preferring the organization when both are
 * empty - a server connected for the organization is available to every agent,
 * which is what somebody adding one on this page is usually after.
 */
function defaultScope(row: McpServerRow, canManageOrganization: boolean): Scope {
  // The empty side first, then the organization's - which is the one an agent
  // can actually be bound to, so it is the right default for a second account.
  if (canManageOrganization && row.organizations.length === 0) return "organization";
  if (row.personals.length === 0) return "personal";
  return canManageOrganization ? "organization" : "personal";
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
/** How many accounts this server holds, across both owners. */
function connectionCount(row: McpServerRow): number {
  return row.organizations.length + row.personals.length;
}

/**
 * The card's one piece of state, as a dot.
 *
 * The worst state wins: a card whose three accounts include one that failed
 * says so, because "mostly working" is not what somebody scanning a grid of
 * sixty servers for a broken one needs to see.
 */
function StateDot({ row }: { row: McpServerRow }) {
  const t = useTranslations("mcp");
  const states = [...row.organizations, ...row.personals].map((c) => connectionState(c));
  if (states.length === 0) return null;
  const worst = states.includes("error")
    ? "error"
    : states.includes("needs-authorization")
      ? "needs-authorization"
      : states.includes("disabled")
        ? "disabled"
        : "connected";

  return (
    <span
      className={cn(
        "ml-auto inline-block h-2 w-2 shrink-0 rounded-full",
        worst === "connected"
          ? "bg-success"
          : worst === "error"
            ? "bg-destructive"
            : "bg-muted-foreground/50",
      )}
      title={t(MCP_STATE_LABEL[worst])}
    />
  );
}
