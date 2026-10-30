"use client";

import { useEffect, useMemo, useState } from "react";
import { Plug, Plus, Settings2 } from "lucide-react";
import { toast } from "sonner";

import {
  Badge,
  Button,
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
import { CardStatus, McpServerCard } from "@/components/mcp/mcp-server-card";
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
import { useCreatedToast } from "@/hooks/use-created-toast";
import { MCP_PAGE_SIZE, useMcpCatalog, useMcpCatalogPage } from "@/hooks/use-mcp-servers";
import { getErrorMessage } from "@/lib/api-error";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import { startMcpOAuth } from "@/lib/mcp-connections-api";
import {
  type McpOAuthClient,
  mcpOAuthClient,
  rememberMcpOAuthReturn,
  secretWithoutClientId,
} from "@/lib/mcp-oauth";
import {
  connectionState,
  CUSTOM_CATEGORY,
  matchingCustomRows,
  categoryLabel,
  customRows,
  freePrefix,
  isReviewed,
  MCP_AUTH_LABEL,
  MCP_STATE_LABEL,
  rowsForEntries,
  slugForPrefix,
} from "@/lib/mcp-servers";
import type { McpServerRow } from "@/lib/mcp-servers";
import { setUrlParam } from "@/lib/utils";
import type { McpAuthKind } from "@/types/mcp";
import type { AudiencePayload } from "@/types/sharing";
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

/**
 * Which server's accounts are open, by key: in the URL so a reload, a shared link
 * and the return from a provider's consent screen all land on that server's
 * accounts rather than on the list (#2301).
 */
const SERVER_PARAM = "server";

/** Where a consent started here comes back to: this page, with the server open. */
function serverReturn(key: string): string {
  const url = new URL(window.location.href);
  url.searchParams.set(SERVER_PARAM, key);
  return `${url.pathname}?${url.searchParams.toString()}`;
}

/** Whether a row is filtered by whether anybody has connected it. */
type StateFilter = "all" | "connected" | "not-connected";

/**
 * A name nothing in this scope holds yet, for a second account on one server.
 *
 * A slug of the entry's key first (the name, not the namespace it lives in - so
 * `com.snitcher/snitcher` seeds `snitcher`, which the tool-prefix pattern accepts,
 * #1628); then `-2`, `-3` and so on. A name is unique per organization and becomes
 * the tool prefix, so seeding one already taken made the form's first submit a
 * guaranteed conflict, and each suffixed candidate stays within the pattern's 32.
 */
function freeName(row: McpServerRow, taken: Set<string>): string | undefined {
  const key = row.entry?.key;
  if (key === undefined) return undefined;
  const base = slugForPrefix(key);
  if (base === "") return undefined;
  return freePrefix(base, taken);
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
/** Whether `scope` already holds an account on this server. */
function hasAccount(scope: Scope, row: McpServerRow): boolean {
  return (scope === "organization" ? row.organizations : row.personals).length > 0;
}

export function McpServerList({ canManageOrganization }: McpServerListProps) {
  const t = useTranslations("mcp");
  const tErrors = useTranslations("errors");
  const { organization, personal, recordTools } = useMcpServers();
  const createdToast = useCreatedToast();
  // The whole curated catalog, for the category filter alone - see below.
  const catalog = useMcpCatalog();
  const [category, setCategory] = useState<string>("all");
  const [state, setState] = useState<StateFilter>("all");
  // What a server asks for, asked of the server like the category: the mirror's
  // rows say it only where the catalog check found it out (#2103).
  const [auth, setAuth] = useState<McpAuthKind | "all">("all");
  // The query, the category and the page all go to the server, because the list
  // is a request now rather than a filter over what the client holds. It held
  // the curated hundred and filtered them locally, which was right until 5,703
  // mirrored registry servers arrived behind them: filtering a page is filtering
  // whatever that page happened to contain, and so is ranking one.
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const listing = useMcpCatalogPage(
    query,
    category === "all" ? "" : category,
    auth === "all" ? "" : auth,
    page,
  );

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
  // The open server by key, read from live data below: a disconnect then shows
  // at once, where a row held from the moment it opened kept the account on
  // screen until the dialog was closed and opened again.
  const [managingKey, setManagingKey] = useState<string | null>(() =>
    typeof window === "undefined"
      ? null
      : new URL(window.location.href).searchParams.get(SERVER_PARAM),
  );
  const manage = (key: string | null) => {
    setManagingKey(key);
    setUrlParam(SERVER_PARAM, key);
  };
  const managing = useMemo((): McpServerRow | null => {
    if (managingKey === null) return null;
    const entry =
      listing.servers.find((each) => each.key === managingKey) ??
      catalog.servers.find((each) => each.key === managingKey);
    if (entry) {
      return rowsForEntries([entry], organization.connections, personal.connections)[0]!;
    }
    return (
      customRows(catalog.servers, organization.connections, personal.connections).find(
        (row) => row.key === managingKey,
      ) ?? null
    );
  }, [
    managingKey,
    listing.servers,
    catalog.servers,
    organization.connections,
    personal.connections,
  ]);
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
      needsLabel: existing === null && hasAccount(scope, row),
    });
  };

  /**
   * **Connect**: straight to the provider's sign-in for a catalog server that
   * signs in - its address, sign-in and prefix are the catalog's, so the form
   * had nothing left to ask - and the form for everything else. **Configure**
   * is the way to that form for the first kind.
   */
  const connect = (scope: Scope, row: McpServerRow) => {
    const name = freeName(row, takenNames(scope));
    // A second account goes through the form, where it is named.
    if (
      row.auth === "oauth" &&
      row.entry !== null &&
      name !== undefined &&
      !hasAccount(scope, row)
    ) {
      void handleOAuth(row, name, scope);
      return;
    }
    openDraft(scope, row, null);
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

  const handleOAuth = async (
    row: McpServerRow,
    name: string,
    scope: Scope = "personal",
    client?: McpOAuthClient,
    audience?: AudiencePayload,
    label?: string,
  ) => {
    setBusyId(row.key);
    try {
      const { authorization_url } = await startMcpOAuth(
        {
          name,
          url: row.url ?? "",
          catalog_key: row.entry?.key,
          ...(label ? { label } : {}),
          ...client,
          ...audience,
        },
        scope,
      );
      rememberMcpOAuthReturn(serverReturn(row.key));
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
          needsLabel: hasAccount("personal", requestedRow),
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
    const name = freeName(requestedRow, taken) ?? slugForPrefix(connectKey);
    startMcpOAuth({ name, url: requestedRow.url ?? "", catalog_key: connectKey }, "personal")
      .then(({ authorization_url }) => {
        rememberMcpOAuthReturn(serverReturn(connectKey));
        window.location.assign(authorization_url);
      })
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
      if (secretWithoutClientId(values.clientId, values.clientSecret)) {
        toast.error(t("clientSecretNeedsId"));
        return;
      }
      closeDraft();
      await handleOAuth(
        { ...row, url },
        name,
        scope,
        mcpOAuthClient(values.clientId, values.clientSecret),
        scope === "organization" ? values.audience : undefined,
        label,
      );
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
          // Provenance for both owners: it groups the row under its catalog entry,
          // and a personal connection without it can never be matched to a
          // binding to each person's own account.
          ...(row.entry ? { catalog_key: row.entry.key } : {}),
          ...(scope === "organization" ? values.audience : {}),
        });
        // The organization's account is what an agent binds, so its toast offers
        // to add it to one (#2075); a member's own is reached through bindings
        // to each person's account, never added by id.
        if (scope === "organization") {
          createdToast(t("connectedForOrg", { name }), { kind: "mcp", id: created.id }, name);
        } else {
          toast.success(t("connectedForYou", { name }));
        }
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
          ...(values.includeInstructions !== existing.include_instructions
            ? { include_instructions: values.includeInstructions }
            : {}),
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
      toast.success(use ? t("nowMainAccount") : t("noLongerMainAccount"));
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
        fill
        namedByPage
        headerTour="mcp-catalog"
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
          <Select
            value={auth}
            onValueChange={(value) => {
              setAuth(value as McpAuthKind | "all");
              setPage(0);
            }}
          >
            <SelectTrigger className="w-auto min-w-36" aria-label={t("authFilter")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("anyAuth")}</SelectItem>
              {(["oauth", "token", "none"] as const).map((kind) => (
                <SelectItem key={kind} value={kind}>
                  {t(MCP_AUTH_LABEL[kind])}
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
        <div className="rise-in grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {visible.map((row, index) => (
            <McpServerCard
              key={row.key}
              name={row.name}
              icon={row.entry?.icon ?? null}
              url={row.url}
              // Nobody here checked a registry server: the description is the
              // publisher's and there is no token hint, which is worth knowing
              // before pasting a credential into it.
              badge={
                isReviewed(row) ? null : (
                  <Badge variant="secondary" className="shrink-0" title={t("fromRegistryHint")}>
                    {t("fromRegistry")}
                  </Badge>
                )
              }
              description={rowDescription(row, t)}
              dataTour={index === 0 ? "mcp-connect" : undefined}
              status={<RowStatus row={row} onManage={() => manage(row.key)} />}
              // A server somebody holds an account on opens its accounts.
              onOpen={connectionCount(row) > 0 ? () => manage(row.key) : undefined}
              // The same two controls on every card, whatever it holds.
              actions={
                <>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => openDraft(defaultScope(row, canManageOrganization), row, null)}
                    disabled={busyId === row.key}
                    title={t("configureNamed", { name: row.name })}
                    aria-label={t("configureNamed", { name: row.name })}
                  >
                    <Settings2 aria-hidden />
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => connect(defaultScope(row, canManageOrganization), row)}
                    disabled={busyId === row.key}
                  >
                    <Plug className="mr-1 h-3.5 w-3.5" />
                    {busyId === row.key ? t("redirecting") : t("connectAction")}
                  </Button>
                </>
              }
            />
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
        onClose={() => manage(null)}
        onConnect={(scope, row) => {
          manage(null);
          connect(scope, row);
        }}
        onEdit={(scope, row, connection) => {
          manage(null);
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
  // Your own account first: it is what most people connecting a server mean, and
  // a shared one deserves a deliberate choice, since every agent in the
  // organization then acts through it. Once you hold your own, a second account
  // is the organization's - where an administrator can make one.
  if (row.personals.length === 0 || !canManageOrganization) return "personal";
  return "organization";
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
function RowStatus({ row, onManage }: { row: McpServerRow; onManage: () => void }) {
  const t = useTranslations("mcp");
  const states = [...row.organizations, ...row.personals].map((c) => connectionState(c));
  if (states.length === 0) return <CardStatus tone="off">{t("cardNotConnected")}</CardStatus>;
  const trouble = states.find((state) => state === "error" || state === "needs-authorization");
  if (trouble) {
    return (
      <CardStatus
        tone="error"
        onClick={onManage}
        label={t("manageConnectionsOn", { name: row.name, count: states.length })}
      >
        {t(MCP_STATE_LABEL[trouble])}
      </CardStatus>
    );
  }
  const yours = row.personals.length;
  const theirs = row.organizations.length;
  return (
    <CardStatus
      tone="live"
      onClick={onManage}
      label={t("manageConnectionsOn", { name: row.name, count: yours + theirs })}
    >
      {yours > 0 && theirs > 0
        ? t("cardYoursAndOrganizations")
        : yours > 0
          ? t("cardYours", { count: yours })
          : t("cardOrganizations", { count: theirs })}
    </CardStatus>
  );
}
