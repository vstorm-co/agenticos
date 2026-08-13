"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Building2, ChevronDown, ExternalLink, Plug, Plus, User } from "lucide-react";
import { toast } from "sonner";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Input,
  Label,
  Pager,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Switch,
  useListControls,
} from "@/components/ui";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { useMcpServers } from "@/hooks";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api-client";
import type { McpConnectionRecord, McpToolInfo } from "@/lib/mcp-connections-api";
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

/** Who a connection belongs to. The whole of what the two columns mean. */
type Scope = "organization" | "personal";

/** Whether a row is filtered by whether anybody has connected it. */
type StateFilter = "all" | "connected" | "not-connected";

/**
 * How a server checks who is calling.
 *
 * The three the platform can do, in either scope. An organization connection
 * may hold an OAuth grant: the common case is a shared service account that one
 * admin consents with and everybody's agents then use. The grant is still that
 * account's at the provider, which is a real operational cost - the dialog says
 * so where the choice is made rather than withholding the choice.
 */
type DraftAuth = "none" | "token" | "oauth";

const AUTH_CHOICES: { value: DraftAuth; labelKey: string; hintKey: string }[] = [
  { value: "none", labelKey: "authChoiceNone", hintKey: "authNoneHint" },
  { value: "token", labelKey: "authApiToken", hintKey: "authTokenHint" },
  { value: "oauth", labelKey: "authOauth", hintKey: "authOauthHint" },
];

/** Keys, like `AUTH_CHOICES` above: a module constant has no translator to reach. */
const SCOPE_LABEL: Record<Scope, string> = {
  organization: "scopeOrganization",
  personal: "scopeYou",
};

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

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}

interface DraftState {
  scope: Scope;
  row: McpServerRow;
  /** The connection being edited, or null when connecting for the first time. */
  existing: McpConnectionRecord | null;
}

interface McpServerListProps {
  /** False for a member without `connections:manage` - the organization column reads only. */
  canManageOrganization: boolean;
}

/**
 * The catalog's frame, drawn whether or not there is anything in it - the
 * always-visible container the vault draws around its keys. The page uses it
 * for the loading and empty states too, so the panel never disappears; only
 * what is inside it changes.
 */
export function ServersCard({ count, children }: { count: number | null; children: ReactNode }) {
  const t = useTranslations("mcp");
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="text-sm">{t("servers")}</CardTitle>
          <CardDescription className="text-xs">
            {/* `null` is "the request has not answered". Rendering "0 servers"
                there would state something nothing has said yet. */}
            {count === null ? <Skeleton className="h-3 w-20" /> : t("serverCount", { count })}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-4">{children}</CardContent>
    </Card>
  );
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
  const [draftName, setDraftName] = useState("");
  const [draftUrl, setDraftUrl] = useState("");
  const [draftToken, setDraftToken] = useState("");
  // How the server is authenticated. A catalog entry states this; a custom one
  // has to be asked, and asking was the gap - the dialog offered a token field
  // and nothing else, so a server behind OAuth could not be added at all.
  const [draftAuth, setDraftAuth] = useState<DraftAuth>("token");
  // The hint under the radio group. It used to be rendered as the *key* -
  // `authTokenHint` on screen, in every locale (#446).
  const hint = AUTH_CHOICES.find((choice) => choice.value === draftAuth)?.hintKey;
  const [clearToken, setClearToken] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toolPicker, setToolPicker] = useState<{
    scope: Scope;
    connection: McpConnectionRecord;
    tools: McpToolInfo[];
    checked: Set<string>;
  } | null>(null);

  const api = (scope: Scope) => (scope === "organization" ? organization : personal);

  const openDraft = (scope: Scope, row: McpServerRow, existing: McpConnectionRecord | null) => {
    setDraft({ scope, row, existing });
    // The catalog knows; a custom server defaults to a token, which is what most
    // self-hosted ones use and what this dialog could always do.
    setDraftAuth(
      existing?.auth_type === "oauth"
        ? "oauth"
        : row.entry?.auth === "oauth"
          ? "oauth"
          : row.entry?.auth === "none"
            ? "none"
            : "token",
    );
    setDraftName(existing?.name ?? row.entry?.key ?? "");
    setDraftUrl(existing?.url ?? row.entry?.url ?? "");
    setDraftToken("");
    setClearToken(false);
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
      toast.error(errorMessage(caught, t("checkFailed")));
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
      toast.error(errorMessage(caught, t("couldNotStartSign")));
      setBusyId(null);
    }
    // On success the browser navigates away - leave the row busy.
  };

  const handleSubmit = async () => {
    if (!draft) return;
    const name = draftName.trim().toLowerCase();
    const url = draftUrl.trim();
    // Only a token connection carries one. Switching to OAuth or None and
    // submitting must not quietly store whatever was typed before.
    const token = draftAuth === "token" ? draftToken.trim() : "";
    if (!NAME_PATTERN.test(name)) {
      toast.error(t("nameMustBeLowercase"));
      return;
    }
    if (!/^https?:\/\//.test(url)) {
      toast.error(t("urlMustStartWithHttp"));
      return;
    }
    const { scope, row, existing } = draft;

    // OAuth is not a row this dialog writes: the grant is obtained at the
    // provider's consent screen and the connection is created by the callback.
    // Sending the form would make an unauthorized bearer connection that then
    // has to be repaired.
    if (draftAuth === "oauth" && existing === null) {
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
          ...(token ? { auth_token: token } : clearToken ? { auth_token: "" } : {}),
        });
        toast.success(t("serverUpdated", { name }));
        setDraft(null);
      }
    } catch (caught) {
      toast.error(errorMessage(caught, t("couldNotSaveServer")));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDisconnect = async (scope: Scope, connection: McpConnectionRecord) => {
    const warning =
      scope === "organization"
        ? t("disconnectOrgWarning", { name: connection.name })
        : t("disconnectWarning", { name: connection.name });
    if (!confirm(warning)) return;
    try {
      await api(scope).remove(connection.id);
      toast.success(t("serverDisconnected", { name: connection.name }));
    } catch (caught) {
      toast.error(errorMessage(caught, t("couldNotDisconnect")));
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
      toast.error(errorMessage(caught, t("couldNotSaveTool")));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={list.query} onChange={list.setQuery} placeholder={t("searchServers")} />
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
      <ServersCard count={rows.length}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {list.visible.map((row) => (
            <Card key={row.key} role="group" aria-label={row.name} className="h-full">
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
      </ServersCard>

      <Dialog open={draft !== null} onOpenChange={(open) => !open && !submitting && setDraft(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {draft === null
                ? ""
                : draft.existing
                  ? t("editNamed", { name: draft.existing.name })
                  : t("connectForScope", { name: draft.row.name, scope: draft.scope })}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="mcp-name">{t("name")}</Label>
              <Input
                id="mcp-name"
                value={draftName}
                onChange={(event) => setDraftName(event.target.value.toLowerCase())}
                placeholder={t("github")}
                maxLength={32}
                className="mt-1.5"
              />
              <p className="text-foreground/45 mt-1 text-[11px]">
                {t("namePrefixesToolNames", { scope: draft?.scope ?? "personal" })}
              </p>
            </div>
            <div>
              <Label htmlFor="mcp-url">{t("serverUrl")}</Label>
              <Input
                id="mcp-url"
                value={draftUrl}
                onChange={(event) => setDraftUrl(event.target.value)}
                placeholder="https://example.com/mcp"
                maxLength={2048}
                className="mt-1.5 font-mono text-sm"
              />
            </div>
            <div>
              <Label>{t("connectAction")}</Label>
              <div
                className="mt-1.5 flex flex-wrap gap-1.5"
                role="radiogroup"
                aria-label={t("connect2")}
              >
                {(["organization", "personal"] as const)
                  .filter((scope) => scope !== "organization" || canManageOrganization)
                  .map((scope) => {
                    const Icon = scope === "organization" ? Building2 : User;
                    return (
                      <button
                        key={scope}
                        type="button"
                        role="radio"
                        aria-checked={draft?.scope === scope}
                        disabled={draft?.existing !== null}
                        onClick={() =>
                          setDraft((previous) => (previous ? { ...previous, scope } : previous))
                        }
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors",
                          draft?.scope === scope
                            ? "border-foreground/30 bg-accent text-foreground"
                            : "border-input text-muted-foreground hover:text-foreground",
                          draft?.existing !== null && "cursor-not-allowed opacity-60",
                        )}
                      >
                        <Icon className="h-3.5 w-3.5" />
                        {t(SCOPE_LABEL[scope])}
                      </button>
                    );
                  })}
              </div>
              <p className="text-muted-foreground mt-1.5 text-xs">
                {draft?.scope === "organization" ? t("everyAgentCanReach") : t("yoursAloneYourOwn")}
              </p>
              {draft?.existing !== null && (
                // Moving a live connection between owners would mean re-sealing
                // its credential under another envelope and changing who may
                // revoke it. Disconnect and connect again is the honest path.
                <p className="text-muted-foreground mt-1 text-xs">
                  {t("existingConnectionCannotChange")}
                </p>
              )}
            </div>

            <div>
              <Label>{t("authentication")}</Label>
              <div
                className="mt-1.5 flex flex-wrap gap-1.5"
                role="radiogroup"
                aria-label={t("authentication2")}
              >
                {AUTH_CHOICES.map((choice) => (
                  <button
                    key={choice.value}
                    type="button"
                    role="radio"
                    aria-checked={draftAuth === choice.value}
                    onClick={() => setDraftAuth(choice.value)}
                    className={cn(
                      "rounded-md border px-3 py-1.5 text-sm transition-colors",
                      draftAuth === choice.value
                        ? "border-foreground/30 bg-accent text-foreground"
                        : "border-input text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {t(choice.labelKey)}
                  </button>
                ))}
              </div>
              <p className="text-muted-foreground mt-1.5 text-xs">
                {hint === undefined ? null : t(hint)}
              </p>
              {draftAuth === "oauth" && draft?.scope === "organization" && (
                // Said once, where the choice is made. The grant is the
                // consenting person's at the provider, so revoking their access
                // there stops the organization's server working until somebody
                // authorizes it again - which is why a shared service account is
                // the right thing to consent with.
                <p className="text-muted-foreground mt-1.5 text-xs">{t("whoeverSignsGrantsIf")}</p>
              )}
            </div>

            <div className={cn(draftAuth !== "token" && "hidden")}>
              <Label htmlFor="mcp-token">{t("accessToken")}</Label>
              {/* The catalog's own advice for *this* server, which used to sit on
                  the card. It is instructions for filling in the field below it,
                  so it belongs next to the field and not in a list somebody is
                  still browsing. Generic guidance is the main reason token setup
                  fails, which is why the backend carries a per-entry hint. */}
              {draft?.row.tokenHint && (
                <p className="text-muted-foreground mt-1.5 text-xs">{draft.row.tokenHint}</p>
              )}
              <Input
                id="mcp-token"
                type="password"
                value={draftToken}
                onChange={(event) => {
                  setDraftToken(event.target.value);
                  if (event.target.value) setClearToken(false);
                }}
                placeholder={
                  draft?.existing?.has_auth_token
                    ? "•••••• (stored - type to replace)"
                    : t("pasteHere")
                }
                maxLength={4096}
                className="mt-1.5 font-mono text-sm"
              />
              <p className="text-foreground/45 mt-1 text-[11px]">
                {draft?.scope === "organization"
                  ? t("useServiceCredentialNot")
                  : t("storedEncryptedNeverShown")}
              </p>
              {draft?.existing?.has_auth_token && !draftToken && (
                <div className="mt-2 flex items-center gap-2">
                  <Switch
                    id="mcp-clear-token"
                    checked={clearToken}
                    onCheckedChange={setClearToken}
                  />
                  <Label htmlFor="mcp-clear-token" className="text-xs font-normal">
                    {t("removeStoredCredential")}
                  </Label>
                </div>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDraft(null)} disabled={submitting}>
              {t("cancel")}
            </Button>
            <Button onClick={handleSubmit} disabled={submitting}>
              {submitting ? t("saving") : draft?.existing ? t("save") : t("connectCheck")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={toolPicker !== null}
        onOpenChange={(open) => !open && !submitting && setToolPicker(null)}
      >
        <DialogContent className="max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("toolsFrom", { name: toolPicker?.connection.name ?? "" })}</DialogTitle>
          </DialogHeader>
          <p className="text-foreground/55 text-xs">
            {t("whichToolsExposed", { scope: toolPicker?.scope ?? "personal" })}
          </p>
          <ul className="border-foreground/10 divide-foreground/8 divide-y rounded-xl border">
            {toolPicker?.tools.map((tool) => (
              <li key={tool.name} className="flex items-start gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <code className="text-foreground bg-foreground/8 rounded px-1.5 py-0.5 font-mono text-xs">
                    {tool.name}
                  </code>
                  {tool.description && (
                    <p className="text-foreground/55 mt-1 line-clamp-2 text-xs">
                      {tool.description}
                    </p>
                  )}
                </div>
                <Switch
                  checked={toolPicker.checked.has(tool.name)}
                  onCheckedChange={(on) =>
                    setToolPicker((previous) => {
                      if (!previous) return previous;
                      const next = new Set(previous.checked);
                      if (on) next.add(tool.name);
                      else next.delete(tool.name);
                      return { ...previous, checked: next };
                    })
                  }
                  aria-label={t("toggleNamed", { name: tool.name })}
                />
              </li>
            ))}
          </ul>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setToolPicker(null)} disabled={submitting}>
              {t("cancel2")}
            </Button>
            <Button
              onClick={handleSaveTools}
              disabled={submitting || toolPicker?.checked.size === 0}
            >
              {submitting ? t("saving2") : t("saveSelection")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
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
