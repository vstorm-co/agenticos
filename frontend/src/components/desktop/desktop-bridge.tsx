"use client";
import { desktopScope } from "@/stores/desktop-preferences-store";
import { isConsolePath } from "@/lib/desktop/paths";
import { useDesktopNotifier } from "@/hooks/use-desktop-notifier";
import { DesktopSetupGate } from "./desktop-setup-gate";
import { DesktopActivityBridge } from "./desktop-activity-bridge";

import { useDesktopSmoothScroll } from "@/hooks/use-desktop-smooth-scroll";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { useAssistantSignals } from "@/hooks/use-assistant-signals";
import { useShellEvent } from "@/hooks/use-desktop";
import { useUnreadNotificationCount } from "@/hooks/use-notifications";
import { usePermissions } from "@/hooks/use-permissions";
import { useApprovals } from "@/hooks/use-runs";
import { useOpenShared } from "@/hooks/use-open-shared";
import { useShell } from "@/hooks/use-shell";
import { parseApprovalDecision, setBadge } from "@/lib/desktop/commands";
import {
  argumentsPreview,
  newApprovals,
  newestOf,
  newNotifications,
  notificationPath,
} from "@/lib/desktop/notices";
import {
  isDesktopShell,
  reportShellFailure,
  SHELL_EVENTS,
  type ShellInfo,
} from "@/lib/desktop/shell";
import { useRouter } from "@/lib/locale-navigation";
import { listNotifications } from "@/lib/notifications-api";
import { Perm } from "@/types/permissions";
import { qk } from "@/lib/query-keys";
import { recordSessionApp } from "@/lib/session-app";
import { useComposerIntentStore } from "@/stores/composer-intent-store";

const APPROVALS_PATH = "/runs?tab=approvals";

/**
 * The console's half of the desktop app, mounted once in the console window:
 * what the shell cannot know without a session, told to it.
 *
 * - The shell's menu changes page through `window.__agenticosNavigate`, a client
 *   navigation, so ⌘1 swaps the page the way a sidebar click does.
 * - The count of what is waiting goes to the Dock icon and the tray.
 * - What arrived since the last look - an inbox row, an approval - becomes a
 *   native notification; an approval carries Approve and Reject, and the choice
 *   comes back here to be made with this page's session, through the same
 *   request the queue's own buttons make.
 * - Files dropped on blobby or the Dock icon open a new chat with them.
 *
 * Nothing on the first look: what was already waiting when the app opened is in
 * the badge, and a burst of notifications for old news is how an app gets its
 * notifications switched off.
 */
export function DesktopBridge() {
  const shell = useShell();
  useDesktopSmoothScroll(isDesktopShell(shell) && shell.window === "main");
  return isDesktopShell(shell) && shell.window === "main" ? <Bridge shell={shell} /> : null;
}

function Bridge({ shell }: { shell: ShellInfo }) {
  const t = useTranslations("desktop.notifications");
  const router = useRouter();
  const { can } = usePermissions();
  const delivery = useDesktopNotifier();
  const sendNotice = delivery.send;
  const canDecide = can(Perm.approvalsDecide);
  const { pendingApprovals } = useAssistantSignals();
  const unread = useUnreadNotificationCount();
  const { approvals, decide } = useApprovals({ enabled: canDecide });
  const requestIntent = useComposerIntentStore((state) => state.request);
  const openShared = useOpenShared();
  // The newest inbox page, re-read whenever the unread count moves.
  const { data: inbox } = useQuery({
    queryKey: qk.desktop.inbox(unread.count),
    queryFn: () => listNotifications(),
  });

  // The sessions list names this app, not the webview's engine.
  useEffect(() => {
    recordSessionApp(shell).catch((error: unknown) =>
      reportShellFailure("could not tell the server which app this is", error),
    );
  }, [shell]);

  useEffect(() => {
    window.__agenticosNavigate = (path: string) => router.push(path);
    return () => {
      delete window.__agenticosNavigate;
    };
  }, [router]);

  useEffect(() => {
    setBadge(pendingApprovals + unread.count).catch((error: unknown) =>
      reportShellFailure("could not set the badge", error),
    );
  }, [pendingApprovals, unread.count]);

  const seenSince = useRef<string | null | undefined>(undefined);
  const seenApprovals = useRef<Set<string> | null>(null);
  const deliveryScope = useRef(delivery.scope);
  useEffect(() => {
    if (deliveryScope.current !== delivery.scope) {
      deliveryScope.current = delivery.scope;
      seenApprovals.current = null;
      seenSince.current = undefined;
    }
  }, [delivery.scope]);
  useEffect(() => {
    if (!canDecide) return;
    const fresh = seenApprovals.current ? newApprovals(seenApprovals.current, approvals) : [];
    seenApprovals.current = new Set(approvals.map((approval) => approval.id));
    for (const approval of fresh) {
      sendNotice(
        {
          kind: "approval",
          title: t("approvalTitle", {
            agent: approval.agent_name ?? t("anAgent"),
            tool: approval.tool_id,
          }),
          body: argumentsPreview(approval.tool_args),
          path: APPROVALS_PATH,
          approval_id: approval.id,
          approve_label: t("approve"),
          reject_label: t("reject"),
        },
        "approval_requested",
        approval.run_id,
      ).catch((error: unknown) => reportShellFailure("could not notify an approval", error));
    }
  }, [approvals, canDecide, t, sendNotice]);

  useEffect(() => {
    if (!inbox) return;
    const rows = inbox.items;
    const fresh = seenSince.current === undefined ? [] : newNotifications(seenSince.current, rows);
    seenSince.current = newestOf(seenSince.current ?? null, rows);
    for (const row of fresh) {
      sendNotice(
        {
          kind: "inbox",
          title: row.agent?.name ?? t("inboxTitle"),
          body: row.summary,
          path: notificationPath(row),
        },
        row.event_type,
      ).catch((error: unknown) => reportShellFailure("could not notify", error));
    }
  }, [inbox, t, sendNotice]);

  useShellEvent("desktop:question", (value) => {
    if (
      !value ||
      typeof value !== "object" ||
      !("account" in value) ||
      !("organization" in value) ||
      !("title" in value) ||
      !("path" in value)
    )
      return;
    if (
      typeof value.account !== "string" ||
      typeof value.organization !== "string" ||
      typeof value.title !== "string" ||
      typeof value.path !== "string" ||
      !isConsolePath(value.path) ||
      delivery.scope !== desktopScope(value.account, value.organization)
    )
      return;
    void delivery
      .send(
        { kind: "inbox", title: value.title, body: t("questionBody"), path: value.path },
        "background_task_paused",
      )
      .catch((error: unknown) => reportShellFailure("notifying a live question", error));
  });

  // The voice call shortcut: the shell has brought the chat forward; it
  // starts the call once the agent's readiness is known, as the phone's does.
  useShellEvent(SHELL_EVENTS.start, (payload) => {
    if (payload === "call") requestIntent("call");
    else reportShellFailure("an unknown thing to start", payload);
  });

  // A file dropped on blobby or the Dock icon: a new chat with it - one dropped
  // before this page was up waits for it to arrive.
  useEffect(() => {
    openShared();
  }, [openShared]);
  useShellEvent(SHELL_EVENTS.dropped, openShared);

  useShellEvent(SHELL_EVENTS.approval, (payload) => {
    try {
      const { approval_id, approved } = parseApprovalDecision(payload);
      decide.mutate({ id: approval_id, approved });
    } catch (error) {
      reportShellFailure("a decision from a notification could not be read", error);
    }
  });

  return (
    <>
      <DesktopSetupGate />
      <DesktopActivityBridge />
    </>
  );
}
