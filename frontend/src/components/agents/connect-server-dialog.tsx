"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { McpConnectionDialog } from "@/components/mcp/mcp-connection-dialog";
import type { ConnectionFormValues, DraftState } from "@/components/mcp/mcp-server-list-types";
import { getErrorMessage } from "@/lib/api-error";
import { startMcpOAuth } from "@/lib/mcp-connections-api";
import { rowForEntry } from "@/lib/mcp-servers";
import { useOrgMcpConnections } from "@/hooks/use-org-mcp-connections";
import type { McpCatalogEntry } from "@/types/mcp";

/** What the server itself accepts as a name; it becomes the tool prefix. */
const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;

/**
 * Connect an organization's MCP server without leaving the Builder.
 *
 * Deliberately narrower than the connect flow on `/mcp-servers`, which also
 * edits, disconnects, picks tools and manages a person's own connections. This
 * one does the single thing the Builder needs - the agent can only bind the
 * organization's servers, so that is the only scope it offers - and it exists
 * because the alternative was a link that threw away an unsaved draft and asked
 * somebody to find their way back.
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
}: {
  /** The catalog entry being connected, or null when the dialog is closed. */
  entry: McpCatalogEntry | null;
  onClose: () => void;
  /** The new connection's id, so the caller can bind it straight away. */
  onConnected?: (connectionId: string) => void;
}) {
  // Split so the form below never has a nullable entry. Reading one inside the
  // submit handler meant a `catalog_key` fallback for a state the handler
  // cannot be in - a branch no test could reach, which is a branch to delete
  // rather than one to cover.
  if (entry === null) return null;
  return <ConnectForm entry={entry} onClose={onClose} onConnected={onConnected} />;
}

function ConnectForm({
  entry,
  onClose,
  onConnected,
}: {
  entry: McpCatalogEntry;
  onClose: () => void;
  onConnected?: (connectionId: string) => void;
}) {
  const t = useTranslations("mcp");
  const tErrors = useTranslations("errors");
  const { create } = useOrgMcpConnections();
  const [submitting, setSubmitting] = useState(false);

  // The dialog speaks `DraftState`, and `rowForEntry` is what turns a catalog
  // entry into one - shared with the servers page, so a row here and a row
  // there cannot drift into two shapes.
  const draft: DraftState = { scope: "organization", row: rowForEntry(entry), existing: null };

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
      const tab = window.open("", "_blank", "noopener");
      setSubmitting(true);
      try {
        const { authorization_url } = await startMcpOAuth({ name, url }, "organization");
        if (tab) {
          tab.location.href = authorization_url;
        } else {
          // Blocked anyway. Better a navigation the person did not expect than
          // a consent screen that never opens and no explanation.
          window.location.assign(authorization_url);
        }
        onClose();
        toast.info(t("finishConsentThenReturn"));
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
        // rather than guessing from a URL somebody may later edit.
        catalog_key: entry.key,
      });
      onClose();
      // `connected` is the bare state word; this is the sentence the servers
      // page uses for the same event.
      toast.success(t("connectedForOrg", { name: created.name }));
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
      // The agent can only bind the organization's servers, so this is the only
      // scope worth offering - and offering the other would be offering a
      // choice that guarantees publishing fails.
      canManageOrganization
      onSubmit={handleSubmit}
    />
  );
}
