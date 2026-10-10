"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { MCP_OAUTH_PARAMS, mcpOAuthMessage, readMcpOAuthOutcome } from "@/lib/mcp-oauth";

import { useCreatedToast } from "./use-created-toast";

/**
 * Announces the outcome of an MCP OAuth consent, once, on arrival.
 *
 * The provider redirects the browser here, so the query string is the only place
 * the outcome can be told - and reading it is what nothing did (#657). The
 * parameters are stripped as they are read, so a reload does not re-announce a
 * consent given ten minutes ago; `window.location` is read rather than
 * `useSearchParams` because stripping them is then also what stops React's
 * second pass from saying it twice.
 */
export function useMcpOAuthOutcome(): void {
  const t = useTranslations("mcp");
  const createdToast = useCreatedToast();

  useEffect(() => {
    const outcome = readMcpOAuthOutcome(window.location.search);
    if (outcome === null) return;
    const url = new URL(window.location.href);
    for (const param of MCP_OAUTH_PARAMS) url.searchParams.delete(param);
    window.history.replaceState({}, "", url.toString());
    const message = mcpOAuthMessage(outcome, t);
    if (outcome.status !== "success") toast.error(message);
    // The organization's account is what an agent binds, so its return offers
    // to add it to one, as connecting one with a key does (#2075).
    else if (outcome.connectionId !== null) {
      createdToast(message, { kind: "mcp", id: outcome.connectionId }, outcome.name);
    } else toast.success(message);
  }, [createdToast, t]);
}
