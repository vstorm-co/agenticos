"use client";

import { useCallback } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getPathname } from "@/lib/locale-navigation";
import { qk } from "@/lib/query-keys";
import { ROUTES } from "@/lib/constants";

const TOOLKITS = new Set([
  "gmail",
  "googledrive",
  "googlecalendar",
  "outlook",
  "slack",
  "notion",
  "github",
]);

export function managedAppToolkit(catalogKey: string | null): string | null {
  if (!catalogKey?.startsWith("composio-")) return null;
  const toolkit = catalogKey.slice("composio-".length);
  return TOOLKITS.has(toolkit) ? toolkit : null;
}

/** Keep a paused chat or an unsaved builder in place while the managed journey runs. */
export function useManagedAppConnect() {
  const locale = useLocale();
  const t = useTranslations("mcp");
  const queryClient = useQueryClient();
  return useCallback(
    (catalogKey: string, options: { keepThisTab?: boolean; sameTab?: boolean } = {}) => {
      const toolkit = managedAppToolkit(catalogKey);
      if (!toolkit) return;
      const href = getPathname({
        locale,
        href: { pathname: ROUTES.CONNECTORS, query: { app: toolkit } },
      });
      if (options.sameTab && !options.keepThisTab) {
        window.location.assign(href);
        return;
      }
      const tab = window.open("", "_blank");
      if (!tab) {
        // Never fall back to replacing a tab that owns an active or paused run.
        toast.error(t("consentTabBlocked"));
        return;
      }
      tab.opener = null;
      const refresh = () => {
        void queryClient.invalidateQueries({ queryKey: qk.appConnections.all() });
        void queryClient.invalidateQueries({ queryKey: qk.mcpConnections.all() });
        void queryClient.invalidateQueries({ queryKey: qk.mcpServers.lists() });
        void queryClient.invalidateQueries({ queryKey: qk.mcpServers.entries() });
      };
      window.addEventListener("focus", refresh, { once: true });
      tab.location.href = href;
      toast.info(t("finishConsentThenReturn"));
    },
    [locale, queryClient, t],
  );
}
