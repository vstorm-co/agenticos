"use client";
import { qk } from "@/lib/query-keys";
import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { usePathname, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Button, Switch } from "@/components/ui";
import { SectionCard } from "@/components/settings/settings-section";
import { useAuthStore } from "@/stores";
import { useTenantId } from "@/hooks/use-organizations";
import { useShell } from "@/hooks/use-shell";
import { isMobileShell, reportShellFailure } from "@/lib/desktop/shell";
import {
  readMobilePushPreferences,
  saveMobilePushPreferences,
  setPushFocus,
} from "@/lib/mobile/notifications";
function usePreferences() {
  const user = useAuthStore((s) => s.user?.id);
  const org = useTenantId();
  const key = qk.mobile.pushPreferences(user, org);
  const client = useQueryClient();
  const t = useTranslations("mobile.setup");
  const query = useQuery({ queryKey: key, queryFn: readMobilePushPreferences, enabled: !!user });
  const save = useMutation({
    mutationFn: saveMobilePushPreferences,
    onSuccess: (data) => client.setQueryData(key, data),
    onError: () => toast.error(t("failed")),
  });
  return { query, save };
}
export function MobileNotificationPreferences() {
  const t = useTranslations("mobile.setup");
  const { query, save } = usePreferences();
  return (
    <SectionCard title={t("privacyTitle")} description={t("privacyHint")}>
      {query.data ? (
        <div className="flex items-center justify-between gap-3">
          <label htmlFor="phone-previews" className="text-sm">
            {t("hidePreviews")}
          </label>
          <Switch
            id="phone-previews"
            checked={query.data.hide_previews}
            disabled={save.isPending}
            onCheckedChange={(hide_previews) =>
              query.data && save.mutate({ ...query.data, hide_previews })
            }
          />
        </div>
      ) : (
        <Button variant="outline" disabled={query.isPending} onClick={() => query.refetch()}>
          {t(query.isPending ? "checking" : "retry")}
        </Button>
      )}
      {!!query.data?.muted_conversations.length && (
        <p className="text-muted-foreground mt-3 text-xs">
          {t("mutedCount", { count: query.data.muted_conversations.length })}
        </p>
      )}
    </SectionCard>
  );
}
export function MobileConversationNotifications({
  conversationId,
}: {
  conversationId: string | null;
}) {
  const { query, save } = usePreferences();
  const t = useTranslations("mobile.setup");
  if (!conversationId || !query.data) return null;
  const prefs = query.data;
  const muted = prefs.muted_conversations.includes(conversationId);
  return (
    <Button
      variant="ghost"
      size="sm"
      className="mt-3 w-full"
      disabled={save.isPending}
      aria-pressed={muted}
      onClick={() =>
        save.mutate({
          ...prefs,
          muted_conversations: muted
            ? prefs.muted_conversations.filter((id) => id !== conversationId)
            : [...prefs.muted_conversations, conversationId],
        })
      }
    >
      {t(muted ? "unmute" : "mute")}
    </Button>
  );
}
/** A short server lease expires even if the process is killed without cleanup. */
export function MobilePushFocus() {
  const shell = useShell();
  const user = useAuthStore((s) => s.user?.id);
  const path = usePathname();
  const params = useSearchParams();
  const id = /\/chat\/?$/.test(path) ? params.get("id") : null;
  const queued = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => {
    if (!isMobileShell(shell) || !user) return;
    let alive = true;
    const refresh = () => {
      queued.current = queued.current.then(async () => {
        if (!alive) return;
        const visible = document.visibilityState === "visible" && document.hasFocus();
        try {
          await setPushFocus(visible ? id : null);
        } catch (error) {
          reportShellFailure("could not update phone notification focus", error);
        }
      });
    };
    refresh();
    const timer = setInterval(refresh, 30_000);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("focus", refresh);
    window.addEventListener("blur", refresh);
    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("blur", refresh);
    };
  }, [shell, id, user]);
  return null;
}
