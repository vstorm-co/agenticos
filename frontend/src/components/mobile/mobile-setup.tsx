"use client";
import { qk } from "@/lib/query-keys";
import { useEffect, useState, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import {
  Bell,
  Bot,
  Check,
  CircleAlert,
  Fingerprint,
  LoaderCircle,
  RefreshCw,
  UserRound,
} from "lucide-react";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui";
import { SectionCard } from "@/components/settings/settings-section";
import { useShell } from "@/hooks/use-shell";
import { useAgents } from "@/hooks/use-agents";
import { useTenantId } from "@/hooks/use-organizations";
import { useAuthStore } from "@/stores";
import { isMobileShell } from "@/lib/desktop/shell";
import { mobileSettings } from "@/lib/mobile/settings";
import { iphonePush } from "@/lib/mobile/apns";
import { phonePushStatus } from "@/lib/mobile/push";
import Link from "next/link";
import { IphonePush } from "./iphone-push";
import { PhonePush } from "./phone-push";

type State = "ready" | "missing" | "checking" | "error" | "unavailable";
export function mobileNotificationState(
  platform: string,
  value: Awaited<ReturnType<typeof iphonePush>> | Awaited<ReturnType<typeof phonePushStatus>>,
): State {
  if (platform === "ios" && "configured" in value)
    return value.configured && value.permission === "granted" && value.token ? "ready" : "missing";
  if ("subscription" in value)
    return value.subscription && (value.permission === undefined || value.permission === "granted")
      ? "ready"
      : "missing";
  return "error";
}
function useSetup(platform: string) {
  const userId = useAuthStore((s) => s.user?.id);
  const tenant = useTenantId();
  const agents = useAgents({ enabled: !!userId });
  const settings = useQuery({
    queryKey: qk.mobile.settings(),
    staleTime: 5000,
    queryFn: mobileSettings,
    refetchOnWindowFocus: "always",
  });
  const notifications = useQuery<
    Awaited<ReturnType<typeof iphonePush>> | Awaited<ReturnType<typeof phonePushStatus>>
  >({
    queryKey: qk.mobile.push(userId, tenant),
    staleTime: 5000,
    queryFn: () => (platform === "ios" ? iphonePush() : phonePushStatus()),
    refetchOnWindowFocus: "always",
    refetchInterval: 15_000,
    retry: false,
  });
  const refetchNotifications = notifications.refetch;
  useEffect(() => {
    const refresh = () => {
      void refetchNotifications();
    };
    window.addEventListener("mobile:push-changed", refresh);
    return () => window.removeEventListener("mobile:push-changed", refresh);
  }, [refetchNotifications]);
  const items: { key: "account" | "agent" | "lock" | "notifications"; state: State }[] = [
    { key: "account", state: userId ? "ready" : "missing" },
    {
      key: "agent",
      state: agents.error
        ? "error"
        : agents.isLoading
          ? "checking"
          : agents.agents.some((a) => a.status === "published" && a.can_run)
            ? "ready"
            : "missing",
    },
    {
      key: "lock",
      state: settings.isError
        ? "error"
        : !settings.data
          ? "checking"
          : !settings.data.biometric_available
            ? "unavailable"
            : settings.data.biometric_lock
              ? "ready"
              : "missing",
    },
    {
      key: "notifications",
      state: notifications.isError
        ? "error"
        : !notifications.data
          ? "checking"
          : mobileNotificationState(platform, notifications.data),
    },
  ];
  return {
    items,
    scope: userId && tenant ? JSON.stringify([userId, tenant]) : null,
    refresh: () => {
      void agents.refetch();
      void settings.refetch();
      void notifications.refetch();
    },
  };
}
const ICONS = { account: UserRound, agent: Bot, lock: Fingerprint, notifications: Bell };
function Panel({ platform }: { platform: string }) {
  const t = useTranslations("mobile.setup");
  const setup = useSetup(platform);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-muted-foreground text-sm">{t("hint")}</p>
        <Button variant="ghost" size="icon" aria-label={t("retry")} onClick={setup.refresh}>
          <RefreshCw className="size-4" />
        </Button>
      </div>
      <div className="divide-y rounded-xl border px-4">
        {setup.items.map((item) => {
          const Icon = ICONS[item.key];
          const Status =
            item.state === "ready" ? Check : item.state === "checking" ? LoaderCircle : CircleAlert;
          return (
            <div key={item.key} className="flex items-center gap-3 py-3">
              <Icon className="text-muted-foreground size-5 shrink-0" aria-hidden />
              <div className="flex-1">
                <p className="text-sm font-medium">{t(item.key)}</p>
                <p className="text-muted-foreground flex items-center gap-1 text-xs">
                  <Status className="size-3" aria-hidden />
                  {t(item.state)}
                </p>
              </div>
              {item.state === "missing" && item.key === "agent" && (
                <Button variant="outline" size="sm" asChild>
                  <Link href="/agents">{t("open")}</Link>
                </Button>
              )}
            </div>
          );
        })}
      </div>
      {platform === "ios" ? <IphonePush /> : <PhonePush />}
      <p className="text-muted-foreground text-xs">{t("contextPermissions")}</p>
    </div>
  );
}
export function MobileSetupPanel() {
  const shell = useShell();
  const t = useTranslations("mobile.setup");
  return isMobileShell(shell) ? (
    <SectionCard title={t("title")}>
      <Panel platform={shell.platform} />
    </SectionCard>
  ) : null;
}
export function MobileSetupGate() {
  const shell = useShell();
  return isMobileShell(shell) ? <Gate platform={shell.platform} /> : null;
}
function Gate({ platform }: { platform: string }) {
  const t = useTranslations("mobile.setup");
  const setup = useSetup(platform);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const settled = setup.items.every((i) => i.state !== "checking");
  // The missing set changes when permissions are revoked, even for old users.
  const fingerprint = JSON.stringify(
    setup.items.filter((i) => i.state === "missing").map((i) => i.key),
  );
  const key = setup.scope ? `agenticos:mobile-setup:v1:${setup.scope}` : null;
  const reviewed = useSyncExternalStore(
    subscribeReview,
    () => {
      if (!key) return undefined;
      try {
        return localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    () => undefined,
  );
  const signature = JSON.stringify([key, fingerprint]);
  const open =
    !!key &&
    reviewed !== undefined &&
    settled &&
    fingerprint !== "[]" &&
    reviewed !== fingerprint &&
    dismissed !== signature;
  const close = () => {
    if (key) {
      try {
        localStorage.setItem(key, fingerprint);
        window.dispatchEvent(new Event(REVIEW_EVENT));
      } catch {
        /* The in-memory dismissal still lasts for this connection. */
      }
    }
    setDismissed(signature);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!value) close();
      }}
    >
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("welcome")}</DialogDescription>
        </DialogHeader>
        <Panel platform={platform} />
        <DialogFooter>
          <Button variant="outline" asChild onClick={close}>
            <Link href="/settings/mobile">{t("settings")}</Link>
          </Button>
          <Button onClick={close}>{t("continue")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const REVIEW_EVENT = "agenticos:mobile-setup-reviewed";
function subscribeReview(notify: () => void) {
  window.addEventListener("storage", notify);
  window.addEventListener(REVIEW_EVENT, notify);
  return () => {
    window.removeEventListener("storage", notify);
    window.removeEventListener(REVIEW_EVENT, notify);
  };
}
