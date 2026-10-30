"use client";
import { qk } from "@/lib/query-keys";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ShieldCheck, Server, RefreshCw } from "lucide-react";
import { Button, Switch } from "@/components/ui";
import { SectionCard } from "@/components/settings/settings-section";
import { useShell } from "@/hooks/use-shell";
import { isMobileShell } from "@/lib/desktop/shell";
import { chooseMobileServer, mobileSettings, setMobileLock } from "@/lib/mobile/settings";

export function MobileSettingsPanel() {
  const shell = useShell();
  return isMobileShell(shell) ? <Settings platform={shell.platform} /> : null;
}
function Settings({ platform }: { platform: string }) {
  const t = useTranslations("mobile.setup");
  const settings = useQuery({
    queryKey: qk.mobile.settings(),
    queryFn: mobileSettings,
    refetchOnWindowFocus: "always",
  });
  const lock = useMutation({
    mutationFn: setMobileLock,
    onSuccess: () => settings.refetch(),
    onError: () => toast.error(t("failed")),
  });
  const change = useMutation({
    mutationFn: () => chooseMobileServer(platform),
    onError: () => toast.error(t("switchFailed")),
  });
  return (
    <SectionCard title={t("deviceTitle")} description={t("deviceHint")}>
      <div className="space-y-5">
        {settings.isPending ? (
          <p role="status">{t("checking")}</p>
        ) : settings.isError ? (
          <Button variant="outline" onClick={() => settings.refetch()}>
            <RefreshCw className="mr-2 size-4" />
            {t("retry")}
          </Button>
        ) : (
          <>
            <div className="flex items-center gap-3">
              <ShieldCheck className="text-muted-foreground size-5 shrink-0" aria-hidden />
              <div className="flex-1">
                <label htmlFor="mobile-lock" className="text-sm font-medium">
                  {t("lock")}
                </label>
                <p className="text-muted-foreground text-xs">
                  {t(
                    settings.data.biometric_managed
                      ? "managed"
                      : settings.data.biometric_available
                        ? "lockHint"
                        : "unavailable",
                  )}
                </p>
              </div>
              <Switch
                id="mobile-lock"
                checked={settings.data.biometric_lock}
                disabled={
                  lock.isPending ||
                  settings.data.biometric_managed ||
                  !settings.data.biometric_available
                }
                onCheckedChange={(value) => lock.mutate(value)}
              />
            </div>
            <div className="flex items-center gap-3">
              <Server className="text-muted-foreground size-5 shrink-0" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {settings.data.servers.find((s) => s.url === settings.data.active)?.name ??
                    settings.data.active}
                </p>
                <p className="text-muted-foreground truncate text-xs">{settings.data.active}</p>
              </div>
              <Button
                variant="outline"
                disabled={change.isPending || settings.data.locked_server}
                onClick={() => change.mutate()}
              >
                {t(change.isPending ? "switching" : "servers")}
              </Button>
            </div>
            <p className="text-muted-foreground text-xs">{t("serverHint")}</p>
          </>
        )}
      </div>
    </SectionCard>
  );
}
