"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plug, Settings2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { McpConnectionDialog } from "@/components/mcp/mcp-connection-dialog";
import type { AudiencePayload } from "@/types/sharing";
import type {
  ConnectionFormValues,
  DraftState,
  Scope,
} from "@/components/mcp/mcp-server-list-types";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { startMcpOAuth } from "@/lib/mcp-connections-api";
import { mcpOAuthClient, rememberMcpOAuthReturn, secretWithoutClientId } from "@/lib/mcp-oauth";
import { freePrefix, rowForEntry, slugForPrefix } from "@/lib/mcp-servers";
import { EVERYONE, audiencePayload } from "@/components/sharing/audience-picker";
import { useMcpConnections } from "@/hooks/use-mcp-connections";
import { useOrgMcpConnections } from "@/hooks/use-org-mcp-connections";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { McpCatalogEntry } from "@/types/mcp";

/** What the server itself accepts as a name; it becomes the tool prefix. */
const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;

/** Either scope's `create`, narrowed to the fields this dialog sends. */
type CreateConnection<T extends McpConnectionRecord> = (
  input: {
    name: string;
    url: string;
    auth_token?: string;
    catalog_key: string;
  } & Partial<AudiencePayload>,
) => Promise<T>;

interface ConnectDialogProps<T extends McpConnectionRecord = McpConnectionRecord> {
  /** The catalog entry being connected, or null when the dialog is closed. */
  entry: McpCatalogEntry | null;
  onClose: () => void;
  /**
   * The new connection, checked, so the caller can bind it straight away - and
   * offer its tools from the check that just ran (#2073).
   */
  onConnected?: (connection: T) => void;
  /**
   * Where an OAuth consent should bring the browser back to, as a path on this
   * app. Given, the consent runs in *this* tab and returns here - right for a
   * chat, which has nothing unsaved to lose and a conversation to come back to.
   * Absent, it opens in a new tab and lands on the servers page, which is what
   * the Builder wants for a draft it must not lose.
   */
  returnTo?: string;
  /**
   * Never navigate this tab, even when the consent tab is blocked: say so
   * instead. For a caller whose tab holds something navigating would end - a
   * chat run paused until the connection is made.
   */
  keepThisTab?: boolean;
}

/**
 * Connect an organization's MCP server without leaving the Builder.
 *
 * Deliberately narrower than the connect flow on `/mcp-servers`, which also
 * edits, disconnects, picks tools and manages a person's own connections. This
 * one does the single thing the Builder needs - an organization binding names
 * the organization's connection, so that is the only scope it offers - and it
 * exists because the alternative was a link that threw away an unsaved draft and
 * asked somebody to find their way back.
 *
 * **OAuth opens a tab rather than navigating.** The consent screen is the
 * provider's and there is no way to stay on the page for it, but there is a way
 * not to lose the agent being edited. The tab is opened on the click itself,
 * before the request that produces the URL: opened afterwards, in the callback
 * of an await, a popup blocker treats it as unprompted and eats it.
 */
export function ConnectServerDialog({
  entry,
  onClose,
  onConnected,
}: ConnectDialogProps<OrgMcpConnectionRecord>) {
  // Split so the form below never has a nullable entry. Reading one inside the
  // submit handler meant a `catalog_key` fallback for a state the handler
  // cannot be in - a branch no test could reach, which is a branch to delete
  // rather than one to cover. The hook lives below the split too: a closed
  // dialog on a page with no query client must not reach for one.
  if (entry === null) return null;
  return <OrgConnectForm entry={entry} onClose={onClose} onConnected={onConnected} />;
}

function OrgConnectForm(
  props: ConnectDialogProps<OrgMcpConnectionRecord> & { entry: McpCatalogEntry },
) {
  const { create, connections } = useOrgMcpConnections();
  return <ConnectForm {...props} scope="organization" create={create} held={connections} />;
}

/**
 * Connect one of *your own* MCP accounts, from wherever an agent needs it.
 *
 * The same form the Builder uses for the organization's, on the personal scope:
 * what a chat opens when an agent bound to each person's own account finds this
 * person has none. Carries the catalog key, because a personal connection
 * without one can never be matched to the binding that asked for it.
 */
export function ConnectOwnServerDialog({
  entry,
  onClose,
  onConnected,
  returnTo,
  keepThisTab,
}: ConnectDialogProps) {
  if (entry === null) return null;
  return (
    <OwnConnectForm
      entry={entry}
      onClose={onClose}
      onConnected={onConnected}
      returnTo={returnTo}
      keepThisTab={keepThisTab}
    />
  );
}

function OwnConnectForm(props: ConnectDialogProps & { entry: McpCatalogEntry }) {
  const { create, connections } = useMcpConnections();
  return <ConnectForm {...props} scope="personal" create={create} held={connections} />;
}

function ConnectForm<T extends McpConnectionRecord>({
  entry,
  scope,
  create,
  held,
  onClose,
  onConnected,
  returnTo,
  keepThisTab,
}: {
  entry: McpCatalogEntry;
  scope: Scope;
  create: CreateConnection<T>;
  /** This scope's connections: a second account on `entry` is named, under a free prefix. */
  held: readonly Held[];
  onClose: () => void;
  onConnected?: (connection: T) => void;
} & ConsentOptions) {
  const t = useTranslations("mcp");
  const tErrors = useTranslations("errors");
  const [submitting, setSubmitting] = useState(false);
  const consent = useConsent(scope, { returnTo, keepThisTab });

  // The dialog speaks `DraftState`, and `rowForEntry` is what turns a catalog
  // entry into one - shared with the servers page, so a row here and a row
  // there cannot drift into two shapes.
  const another = heldOn(held, entry);
  const draft: DraftState = {
    scope,
    row: rowForEntry(entry),
    existing: null,
    ...(another
      ? {
          needsLabel: true,
          suggestedName: freePrefix(
            slugForPrefix(entry.key),
            new Set(held.map((connection) => connection.name)),
          ),
        }
      : {}),
  };

  const handleSubmit = async (values: ConnectionFormValues) => {
    const name = values.name.trim().toLowerCase();
    const url = values.url.trim();
    if (!NAME_PATTERN.test(name)) {
      toast.error(t("nameMustBeLowercase"));
      return;
    }
    if (!/^https?:\/\//.test(url)) {
      toast.error(t("urlMustStartWithHttp"));
      return;
    }

    if (values.auth === "oauth") {
      if (secretWithoutClientId(values.clientId, values.clientSecret)) {
        toast.error(t("clientSecretNeedsId"));
        return;
      }
      setSubmitting(true);
      const label = values.label.trim();
      const started = await consent({
        name,
        url,
        catalog_key: entry.key,
        ...(label ? { label } : {}),
        ...mcpOAuthClient(values.clientId, values.clientSecret),
        ...(scope === "organization" ? values.audience : {}),
      });
      setSubmitting(false);
      if (started) onClose();
      return;
    }

    setSubmitting(true);
    try {
      const created = await create({
        name,
        url,
        ...(values.label.trim() ? { label: values.label.trim() } : {}),
        auth_token: values.auth === "token" ? values.token.trim() : undefined,
        // Provenance, so the picker groups it under the entry it came from
        // rather than guessing from a URL somebody may later edit - and, for a
        // personal connection, what a binding to each person's own account
        // matches it on.
        catalog_key: entry.key,
        ...(scope === "organization" ? values.audience : {}),
      });
      onClose();
      // `connected` is the bare state word; these are the sentences the servers
      // page uses for the same event.
      toast.success(
        scope === "organization"
          ? t("connectedForOrg", { name: created.name })
          : t("connectedForYou", { name: created.name }),
      );
      onConnected?.(created);
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <McpConnectionDialog
      draft={draft}
      onClose={onClose}
      submitting={submitting}
      // One scope per dialog, decided by who opened it: the Builder binds the
      // organization's connections, a person connects their own. Offering the
      // other would be offering a choice the caller cannot use.
      canManageOrganization={scope === "organization"}
      onSubmit={handleSubmit}
    />
  );
}

/** What deciding on a second account reads of a connection. */
type Held = Pick<McpConnectionRecord, "name" | "catalog_key">;

function heldOn(held: readonly Held[], entry: McpCatalogEntry): boolean {
  return held.some((connection) => connection.catalog_key === entry.key);
}

interface ConsentOptions {
  returnTo?: string;
  keepThisTab?: boolean;
}

/**
 * Start a provider's consent for a new connection; true once it is under way.
 *
 * With somewhere to return to, the consent runs in this tab and the callback
 * brings the browser back. Otherwise a new tab, opened without `noopener` and
 * then severed by hand: a browser that implements the feature returns `null`
 * even though it created the tab, so the success path read that as "popup
 * blocked", navigated the Builder itself to the consent screen, discarded the
 * unsaved draft this flow exists to preserve, and left a blank tab behind. The
 * tab is opened before the first `await`, so it still counts as the click's.
 */
function useConsent(scope: Scope, { returnTo, keepThisTab }: ConsentOptions) {
  const t = useTranslations("mcp");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  return async (input: Parameters<typeof startMcpOAuth>[0]): Promise<boolean> => {
    const tab = returnTo === undefined ? window.open("", "_blank") : null;
    if (tab === null && keepThisTab) {
      toast.error(t("consentTabBlocked"));
      return false;
    }
    if (tab) tab.opener = null;
    try {
      const { authorization_url } = await startMcpOAuth(input, scope);
      // The other tab lands on this server's accounts, where the new one shows.
      const back =
        returnTo ?? (input.catalog_key ? `/mcp-servers?server=${input.catalog_key}` : undefined);
      if (back !== undefined) rememberMcpOAuthReturn(back);
      if (tab) {
        // Back in this tab, the connection made in the other is fetched: focus
        // refetches nothing by default here, so "it appears here once it is
        // authorised" stayed untrue until a reload.
        const refresh = () => {
          window.removeEventListener("focus", refresh);
          void queryClient.invalidateQueries({ queryKey: qk.mcpConnections.all() });
        };
        window.addEventListener("focus", refresh);
        tab.location.href = authorization_url;
      } else {
        // Either this is the return-here flow, or the tab was blocked anyway -
        // and a navigation the person did not expect beats a consent screen
        // that never opens and no explanation.
        window.location.assign(authorization_url);
      }
      if (returnTo === undefined) toast.info(t("finishConsentThenReturn"));
      return true;
    } catch (caught) {
      tab?.close();
      toast.error(getErrorMessage(caught, tErrors, t("couldNotStartSign")));
      return false;
    }
  };
}

/**
 * **Connect** on a catalog server: straight to the provider's sign-in when the
 * catalog already says how it signs in, and the form only where something has
 * to be typed - a token, or a server with no address on record.
 *
 * A server people sign in to needs nothing from anybody before the consent:
 * its address, its sign-in and its prefix are the catalog's, and a form of
 * pre-filled fields with one button under them was a click spent reading
 * them. What it would let somebody change is behind **Configure**, which opens
 * that form with its settings unfolded.
 */
export function useConnectEntry(
  scope: Scope,
  {
    openForm,
    held = [],
    ...options
  }: ConsentOptions & {
    openForm: (entry: McpCatalogEntry) => void;
    /**
     * This scope's connections. Their names are taken for a new one's prefix, and
     * one already on `entry` sends the person to the form, where a second account
     * is named.
     */
    held?: readonly Held[];
  },
) {
  const consent = useConsent(scope, options);
  return (entry: McpCatalogEntry) => {
    if (entry.auth !== "oauth" || entry.url === null || heldOn(held, entry)) {
      openForm(entry);
      return;
    }
    void consent({
      name: freePrefix(
        slugForPrefix(entry.key),
        new Set(held.map((connection) => connection.name)),
      ),
      url: entry.url,
      catalog_key: entry.key,
      ...(scope === "organization" ? audiencePayload(EVERYONE) : {}),
    });
  };
}

/**
 * **Connect** for one of a person's own accounts, with **Configure** beside it
 * for a server that signs in - the one kind **Connect** no longer opens a form
 * for. Owns its dialog, so each place offering a service is one element.
 */
export function ConnectOwnButton({
  entry,
  label,
  disabled,
  returnTo,
  keepThisTab,
}: {
  entry: McpCatalogEntry;
  label: string;
  disabled?: boolean;
} & ConsentOptions) {
  const t = useTranslations("mcp");
  const [formOpen, setFormOpen] = useState(false);
  const connect = useConnectEntry("personal", {
    returnTo,
    keepThisTab,
    openForm: () => setFormOpen(true),
  });
  return (
    <>
      <span className="flex shrink-0 items-center gap-0.5">
        {entry.auth === "oauth" && (
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            disabled={disabled}
            onClick={() => setFormOpen(true)}
            title={t("configureNamed", { name: entry.name })}
            aria-label={t("configureNamed", { name: entry.name })}
          >
            <Settings2 aria-hidden />
          </Button>
        )}
        <Button type="button" size="sm" disabled={disabled} onClick={() => connect(entry)}>
          <Plug className="mr-1 h-3.5 w-3.5" />
          {label}
        </Button>
      </span>
      <ConnectOwnServerDialog
        entry={formOpen ? entry : null}
        onClose={() => setFormOpen(false)}
        returnTo={returnTo}
        keepThisTab={keepThisTab}
      />
    </>
  );
}

/**
 * Sign one of the reader's own accounts in again - one whose grant lapsed, or
 * whose consent was never finished - under the name it already has.
 */
export function useSignInOwn(options: ConsentOptions) {
  const consent = useConsent("personal", options);
  return (connection: McpConnectionRecord) => {
    void consent({
      name: connection.name,
      url: connection.url,
      ...(connection.catalog_key ? { catalog_key: connection.catalog_key } : {}),
    });
  };
}
