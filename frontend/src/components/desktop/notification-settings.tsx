"use client";
import { Bell, BellOff } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Switch } from "@/components/ui";
import { DesktopSetting } from "./desktop-only";
import { SectionCard } from "@/components/settings/settings-section";
import { useAuthStore } from "@/stores";
import { useTenantId } from "@/hooks/use-organizations";
import {
  useDesktopPreferencesStore,
  DEFAULT_DESKTOP_NOTIFICATIONS,
  desktopScope,
  type DesktopNotificationPreferences,
} from "@/stores/desktop-preferences-store";
import { useDesktopReadiness } from "@/hooks/use-desktop-readiness";
import { notify } from "@/lib/desktop/commands";
import { reportShellFailure } from "@/lib/desktop/shell";

const CATEGORIES = [
  "completed",
  "failed",
  "approvals",
  "questions",
  "other",
  "hide_previews",
] as const;
export function DesktopNotificationSettings() {
  const t = useTranslations("desktop.notificationSettings");
  const tenant = useTenantId();
  const user = useAuthStore((s) => s.user?.id);
  const scope = desktopScope(user, tenant);
  const prefs = useDesktopPreferencesStore((s) =>
    scope
      ? (s.notifications[scope] ?? DEFAULT_DESKTOP_NOTIFICATIONS)
      : DEFAULT_DESKTOP_NOTIFICATIONS,
  );
  const save = useDesktopPreferencesStore((s) => s.setNotifications);
  const ready = useDesktopReadiness();
  const [failure, setFailure] = useState(false);
  const set = (patch: Partial<DesktopNotificationPreferences>) => {
    if (scope) save(scope, { ...prefs, ...patch });
  };
  return (
    <SectionCard title={t("title")} description={t("description")}>
      <div className="space-y-5">
        {CATEGORIES.map((key) => (
          <DesktopSetting
            key={key}
            id={`desktop-notify-${key}`}
            label={t(key)}
            hint={key === "hide_previews" ? t("privacyHint") : undefined}
          >
            <Switch
              aria-labelledby={`desktop-notify-${key}`}
              checked={prefs[key]}
              disabled={!scope}
              onCheckedChange={(checked) => set({ [key]: checked })}
            />
          </DesktopSetting>
        ))}
        {ready.status.data?.notifications !== "granted" && (
          <Button
            variant="outline"
            disabled={ready.request.isPending}
            onClick={() => ready.request.mutate("notifications")}
          >
            {t("enable")}
          </Button>
        )}
        <Button
          variant="outline"
          onClick={() => {
            setFailure(false);
            notify({
              kind: "inbox",
              title: t("testTitle"),
              body: t("testBody"),
              path: "/settings/desktop",
            }).catch((error: unknown) => {
              setFailure(true);
              reportShellFailure("test notification", error);
            });
          }}
        >
          {t("test")}
        </Button>
        {failure && (
          <p role="alert" className="text-destructive text-sm">
            {t("failedTest")}
          </p>
        )}
        {prefs.muted_conversations.length > 0 && (
          <Button variant="ghost" onClick={() => set({ muted_conversations: [] })}>
            {t("unmuteAll", { count: prefs.muted_conversations.length })}
          </Button>
        )}
      </div>
    </SectionCard>
  );
}
export function ConversationNotificationToggle({
  conversationId,
}: {
  conversationId: string | null;
}) {
  const t = useTranslations("desktop.notificationSettings");
  const tenant = useTenantId();
  const user = useAuthStore((s) => s.user?.id);
  const scope = desktopScope(user, tenant);
  const prefs = useDesktopPreferencesStore((s) =>
    scope
      ? (s.notifications[scope] ?? DEFAULT_DESKTOP_NOTIFICATIONS)
      : DEFAULT_DESKTOP_NOTIFICATIONS,
  );
  const save = useDesktopPreferencesStore((s) => s.setNotifications);
  if (!scope || !conversationId) return null;
  const muted = prefs.muted_conversations.includes(conversationId);
  return (
    <Button
      variant="ghost"
      size="sm"
      className="mt-3 w-full"
      aria-pressed={muted}
      onClick={() =>
        save(scope, {
          ...prefs,
          muted_conversations: muted
            ? prefs.muted_conversations.filter((id) => id !== conversationId)
            : [...prefs.muted_conversations, conversationId],
        })
      }
    >
      {muted ? <Bell className="size-4" aria-hidden /> : <BellOff className="size-4" aria-hidden />}
      {t(muted ? "unmute" : "mute")}
    </Button>
  );
}
