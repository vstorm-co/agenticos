"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { McpConnectionDialog } from "@/components/mcp/mcp-connection-dialog";
import type {
  ConnectionFormValues,
  DraftState,
  Scope,
} from "@/components/mcp/mcp-server-list-types";
import { getErrorMessage } from "@/lib/api-error";
import { startMcpOAuth } from "@/lib/mcp-connections-api";
import { rememberMcpOAuthReturn } from "@/lib/mcp-oauth";
import { rowForEntry } from "@/lib/mcp-servers";
import { useMcpConnections } from "@/hooks/use-mcp-connections";
import { useOrgMcpConnections } from "@/hooks/use-org-mcp-connections";
import type { McpCatalogEntry } from "@/types/mcp";

/** What the server itself accepts as a name; it becomes the tool prefix. */
const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;

/** What either scope's `create` answers with, as far as this dialog reads it. */
type Created = { id: string; name: string };

/** Either scope's `create`, narrowed to the fields this dialog sends. */
type CreateConnection = (input: {
  name: string;
  url: string;
  auth_token?: string;
  catalog_key: string;
}) => Promise<Created>;

interface ConnectDialogProps {
  /** The catalog entry being connected, or null when the dialog is closed. */
  entry: McpCatalogEntry | null;
  onClose: () => void;
  /** The new connection's id, so the caller can bind it straight away. */
  onConnected?: (connectionId: string) => void;
  /**
   * Where an OAuth consent should bring the browser back to, as a path on this
   * app. Given, the consent runs in *this* tab and returns here - right for a
   * chat, which has nothing unsaved to lose and a conversation to come back to.
   * Absent, it opens in a new tab and lands on the servers page, which is what
   * the Builder wants for a draft it must not lose.
   */
  returnTo?: string;
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
export function ConnectServerDialog({ entry, onClose, onConnected }: ConnectDialogProps) {
  // Split so the form below never has a nullable entry. Reading one inside the
  // submit handler meant a `catalog_key` fallback for a state the handler
  // cannot be in - a branch no test could reach, which is a branch to delete
  // rather than one to cover. The hook lives below the split too: a closed
  // dialog on a page with no query client must not reach for one.
  if (entry === null) return null;
  return <OrgConnectForm entry={entry} onClose={onClose} onConnected={onConnected} />;
}

function OrgConnectForm(props: ConnectDialogProps & { entry: McpCatalogEntry }) {
  const { create } = useOrgMcpConnections();
  return <ConnectForm {...props} scope="organization" create={create} />;
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
}: ConnectDialogProps) {
  if (entry === null) return null;
  return (
    <OwnConnectForm entry={entry} onClose={onClose} onConnected={onConnected} returnTo={returnTo} />
  );
}

function OwnConnectForm(props: ConnectDialogProps & { entry: McpCatalogEntry }) {
  const { create } = useMcpConnections();
  return <ConnectForm {...props} scope="personal" create={create} />;
}

function ConnectForm({
  entry,
  scope,
  create,
  onClose,
  onConnected,
  returnTo,
}: {
  entry: McpCatalogEntry;
  scope: Scope;
  create: CreateConnection;
  onClose: () => void;
  onConnected?: (connectionId: string) => void;
  returnTo?: string;
}) {
  const t = useTranslations("mcp");
  const tErrors = useTranslations("errors");
  const [submitting, setSubmitting] = useState(false);

  // The dialog speaks `DraftState`, and `rowForEntry` is what turns a catalog
  // entry into one - shared with the servers page, so a row here and a row
  // there cannot drift into two shapes.
  const draft: DraftState = { scope, row: rowForEntry(entry), existing: null };

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
      // With somewhere to return to, the consent runs in this tab and the
      // callback brings the browser back. Otherwise a new tab, opened without
      // `noopener` and then severed by hand: a browser that implements the
      // feature returns `null` even though it created the tab, so the success
      // path read that as "popup blocked", navigated the Builder itself to the
      // consent screen, discarded the unsaved draft this dialog exists to
      // preserve, and left a blank tab behind.
      const tab = returnTo === undefined ? window.open("", "_blank") : null;
      if (tab) tab.opener = null;
      setSubmitting(true);
      try {
        const { authorization_url } = await startMcpOAuth(
          { name, url, catalog_key: entry.key },
          scope,
        );
        if (returnTo !== undefined) rememberMcpOAuthReturn(returnTo);
        if (tab) {
          tab.location.href = authorization_url;
        } else {
          // Either this is the return-here flow, or the tab was blocked anyway -
          // and a navigation the person did not expect beats a consent screen
          // that never opens and no explanation.
          window.location.assign(authorization_url);
        }
        onClose();
        if (returnTo === undefined) toast.info(t("finishConsentThenReturn"));
      } catch (caught) {
        tab?.close();
        toast.error(getErrorMessage(caught, tErrors, t("couldNotStartSign")));
      } finally {
        setSubmitting(false);
      }
      return;
    }

    setSubmitting(true);
    try {
      const created = await create({
        name,
        url,
        auth_token: values.auth === "token" ? values.token.trim() : undefined,
        // Provenance, so the picker groups it under the entry it came from
        // rather than guessing from a URL somebody may later edit - and, for a
        // personal connection, what a binding to each person's own account
        // matches it on.
        catalog_key: entry.key,
      });
      onClose();
      // `connected` is the bare state word; these are the sentences the servers
      // page uses for the same event.
      toast.success(
        scope === "organization"
          ? t("connectedForOrg", { name: created.name })
          : t("connectedForYou", { name: created.name }),
      );
      onConnected?.(created.id);
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
