"use client";
import {
  Accessibility,
  Bell,
  Bot,
  Check,
  CircleAlert,
  CircleDashed,
  Cpu,
  Keyboard,
  LoaderCircle,
  Mic,
  Minus,
  Monitor,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { type SetupKey, type SetupState, useDesktopSetup } from "@/hooks/use-desktop-setup";
import { useShell } from "@/hooks/use-shell";
import { retryDesktopScreenshot, SYSTEM_PERMISSIONS } from "@/lib/desktop/readiness";
import { isDesktopShell } from "@/lib/desktop/shell";
import { useRouter } from "@/lib/locale-navigation";
import { useMutation } from "@tanstack/react-query";
import { reportShellFailure } from "@/lib/desktop/shell";
import { cn } from "@/lib/utils";

const ITEM_ICONS: Record<SetupKey, LucideIcon> = {
  account: UserRound,
  device: Monitor,
  agent: Bot,
  model: Cpu,
  screen_capture: ScanLine,
  accessibility: Accessibility,
  microphone: Mic,
  notifications: Bell,
  shortcuts: Keyboard,
};
const STATUS_ICONS: Record<SetupState, LucideIcon> = {
  ready: Check,
  missing: CircleDashed,
  checking: LoaderCircle,
  error: CircleAlert,
  unsupported: Minus,
};

export function ReadinessPanel({ repair }: { repair?: string | null }) {
  const shell = useShell();
  const t = useTranslations("desktop.readiness");
  return isDesktopShell(shell) ? <ReadyItems repair={repair} /> : <p>{t("desktopOnly")}</p>;
}
function ReadyItems({ repair }: { repair?: string | null }) {
  const t = useTranslations("desktop.readiness");
  const setup = useDesktopSetup();
  const router = useRouter();
  const retryScreenshot = useMutation({
    mutationFn: retryDesktopScreenshot,
    onError: (e) => reportShellFailure("retrying screenshot", e),
  });
  return (
    <section className="space-y-4" data-tour="desktop-readiness">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("title")}</h2>
          <p className="text-muted-foreground text-sm">{t("description")}</p>
        </div>
        <Button variant="ghost" size="icon" aria-label={t("refresh")} onClick={setup.refresh}>
          <RefreshCw className="size-4" />
        </Button>
      </div>
      <ul className="divide-border divide-y rounded-xl border px-4">
        {setup.items.map((item) => {
          const Icon = ITEM_ICONS[item.key];
          const StatusIcon = STATUS_ICONS[item.state];
          const permission = SYSTEM_PERMISSIONS.find((key) => key === item.key);
          const repairable = item.state === "missing" || item.state === "error";
          const manage = item.state === "error" || item.key !== "model" || item.href !== undefined;
          return (
            <li
              key={item.key}
              className={cn(
                "flex items-center gap-3 py-3",
                repair === item.key && "bg-accent -mx-4 px-4",
              )}
            >
              <Icon
                className="text-muted-foreground size-5 shrink-0"
                strokeWidth={1.75}
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{t(`items.${item.key}`)}</p>
                <p
                  role="status"
                  className="text-muted-foreground mt-0.5 flex items-center gap-1.5 text-xs"
                >
                  <StatusIcon
                    aria-hidden
                    className={cn(
                      "size-3 shrink-0",
                      item.state === "ready" && "text-green-600 dark:text-green-400",
                      item.state === "checking" && "animate-spin motion-reduce:animate-none",
                      item.state === "error" && "text-destructive",
                    )}
                  />
                  {t(`state.${item.state}`)}
                </p>
                {item.key === "model" && item.state === "missing" && !manage && (
                  <p className="text-muted-foreground text-xs">{t("askAdmin")}</p>
                )}
                {item.key === "agent" && item.state === "missing" && !setup.canManageAgents && (
                  <p className="text-muted-foreground text-xs">{t("askAgentAdmin")}</p>
                )}
              </div>
              {repairable && manage && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={setup.native.request.isPending || setup.link.isPending}
                  onClick={() => {
                    if (item.state === "error") setup.refresh();
                    else if (permission) setup.native.request.mutate(permission);
                    else if (item.key === "device") setup.link.mutate();
                    else if (item.href) router.push(item.href);
                  }}
                >
                  {t(
                    item.state === "error"
                      ? "retry"
                      : permission
                        ? "enable"
                        : item.key === "device"
                          ? "connect"
                          : item.key === "agent"
                            ? "viewAgents"
                            : "configure",
                  )}
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      <p className="text-muted-foreground flex items-start gap-2 text-xs leading-relaxed">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>{t("permissionNote")}</span>
      </p>
      {repair === "screen_capture" && setup.native.status.data?.screen_capture === "granted" && (
        <Button disabled={retryScreenshot.isPending} onClick={() => retryScreenshot.mutate()}>
          {t("retryScreenshot")}
        </Button>
      )}
    </section>
  );
}
