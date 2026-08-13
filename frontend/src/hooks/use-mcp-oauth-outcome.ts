"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { MCP_OAUTH_PARAMS, mcpOAuthMessage, readMcpOAuthOutcome } from "@/lib/mcp-oauth";
import { setUrlParam } from "@/lib/utils";

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

  useEffect(() => {
    const outcome = readMcpOAuthOutcome(window.location.search);
    if (outcome === null) return;
    for (const param of MCP_OAUTH_PARAMS) setUrlParam(param, null);
    const say = outcome.status === "success" ? toast.success : toast.error;
    say(mcpOAuthMessage(outcome, t));
  }, [t]);
}
