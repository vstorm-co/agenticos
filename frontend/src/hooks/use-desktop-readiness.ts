"use client";
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useShell } from "./use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { readDesktopReadiness, requestDesktopPermission } from "@/lib/desktop/readiness";
import { qk } from "@/lib/query-keys";

/** A preflight never prompts. Returning from System Settings rechecks the actual OS state. */
export function useDesktopReadiness() {
  const shell = useShell();
  const desktop = isDesktopShell(shell);
  const client = useQueryClient();
  const t = useTranslations("desktop.readiness");
  const status = useQuery({
    queryKey: qk.desktop.readiness(),
    queryFn: readDesktopReadiness,
    enabled: desktop,
    refetchOnWindowFocus: "always",
    staleTime: 5000,
    refetchInterval: 30_000,
    retry: false,
  });
  useEffect(() => {
    if (!desktop) return;
    // macOS can keep the webview visible while System Settings has focus, so
    // TanStack's visibilitychange listener alone does not notice the return.
    const refresh = () => {
      void client.invalidateQueries({ queryKey: qk.desktop.readiness() });
    };
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [client, desktop]);
  const request = useMutation({
    mutationFn: requestDesktopPermission,
    onSuccess: () => client.invalidateQueries({ queryKey: qk.desktop.readiness() }),
    onError: () => toast.error(t("requestFailed")),
  });
  return { status, request };
}
