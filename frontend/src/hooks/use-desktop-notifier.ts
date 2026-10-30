"use client";
import { useCallback, useRef, useLayoutEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useDesktopActiveRuns } from "./use-desktop-active-runs";
import { useTenantId } from "./use-organizations";
import { useAuthStore } from "@/stores";
import {
  DEFAULT_DESKTOP_NOTIFICATIONS,
  desktopScope,
  useDesktopPreferencesStore,
} from "@/stores/desktop-preferences-store";
import { notify, type Notice } from "@/lib/desktop/commands";
import { readDesktopFocus } from "@/lib/desktop/readiness";
import { shouldNotify } from "@/lib/desktop/notification-policy";
import { qk } from "@/lib/query-keys";

/** Policy runs at delivery time; a late OS result cannot notify a different account. */
export function useDesktopNotifier() {
  const user = useAuthStore((s) => s.user?.id);
  const tenant = useTenantId();
  const scope = desktopScope(user, tenant);
  const preferences = useDesktopPreferencesStore((s) =>
    scope
      ? (s.notifications[scope] ?? DEFAULT_DESKTOP_NOTIFICATIONS)
      : DEFAULT_DESKTOP_NOTIFICATIONS,
  );
  const current = useRef(scope);
  useLayoutEffect(() => {
    current.current = scope;
  }, [scope]);
  const { runs } = useDesktopActiveRuns();
  const client = useQueryClient();
  const t = useTranslations("desktop.notificationSettings");
  const send = useCallback(
    async (notice: Notice, event: string, runId?: string) => {
      if (scope === null) return;
      const conversation = runs.find((run) => run.id === runId)?.conversation_id;
      const path = conversation ? `/chat?id=${conversation}` : notice.path;
      if (!shouldNotify({ event, path, preferences, activeConversation: null, focused: false }))
        return;
      const focus = await client.fetchQuery({
        queryKey: qk.desktop.focus(),
        queryFn: readDesktopFocus,
        staleTime: 200,
      });
      if (
        current.current !== scope ||
        !shouldNotify({
          event,
          path,
          preferences,
          activeConversation: focus.conversation_id,
          focused: focus.focused,
        })
      )
        return;
      if (preferences.hide_previews) {
        await notify({
          kind: "inbox",
          title: t("privateTitle"),
          body: t(
            event === "approval_requested"
              ? "privateApproval"
              : event === "background_task_paused"
                ? "privateQuestion"
                : event === "run_failed"
                  ? "privateFailed"
                  : "privateUpdate",
          ),
          path: notice.path,
        });
      } else await notify(notice);
    },
    [scope, preferences, runs, client, t],
  );
  return { scope, send };
}
