"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { useAssistantSignals } from "@/hooks/use-assistant-signals";
import { useShellEvent } from "@/hooks/use-desktop";
import { useUnreadNotificationCount } from "@/hooks/use-notifications";
import { usePermissions } from "@/hooks/use-permissions";
import { useApprovals } from "@/hooks/use-runs";
import { useShell } from "@/hooks/use-shell";
import { notify, parseApprovalDecision, setBadge } from "@/lib/desktop/commands";
import {
  argumentsPreview,
  newApprovals,
  newestOf,
  newNotifications,
  notificationPath,
} from "@/lib/desktop/notices";
import { isDesktopShell, reportShellFailure, SHELL_EVENTS } from "@/lib/desktop/shell";
import { useRouter } from "@/lib/locale-navigation";
import { listNotifications } from "@/lib/notifications-api";
import { Perm } from "@/types/permissions";
import { qk } from "@/lib/query-keys";

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
 *
 * Nothing on the first look: what was already waiting when the app opened is in
 * the badge, and a burst of notifications for old news is how an app gets its
 * notifications switched off.
 */
export function DesktopBridge() {
  const shell = useShell();
  return isDesktopShell(shell) && shell.window === "main" ? <Bridge /> : null;
}

function Bridge() {
  const t = useTranslations("desktop.notifications");
  const router = useRouter();
  const { can } = usePermissions();
  const canDecide = can(Perm.approvalsDecide);
  const { pendingApprovals } = useAssistantSignals();
  const unread = useUnreadNotificationCount();
  const { approvals, decide } = useApprovals({ enabled: canDecide });
  // The newest inbox page, re-read whenever the unread count moves.
  const { data: inbox } = useQuery({
    queryKey: qk.desktop.inbox(unread.count),
    queryFn: () => listNotifications(),
  });

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

  const seenApprovals = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!canDecide) return;
    const fresh = seenApprovals.current ? newApprovals(seenApprovals.current, approvals) : [];
    seenApprovals.current = new Set(approvals.map((approval) => approval.id));
    for (const approval of fresh) {
      notify({
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
      }).catch((error: unknown) => reportShellFailure("could not notify an approval", error));
    }
  }, [approvals, canDecide, t]);

  const seenSince = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (!inbox) return;
    const rows = inbox.items;
    const fresh = seenSince.current === undefined ? [] : newNotifications(seenSince.current, rows);
    seenSince.current = newestOf(seenSince.current ?? null, rows);
    for (const row of fresh) {
      notify({
        kind: "inbox",
        title: row.agent?.name ?? t("inboxTitle"),
        body: row.summary,
        path: notificationPath(row),
      }).catch((error: unknown) => reportShellFailure("could not notify", error));
    }
  }, [inbox, t]);

  useShellEvent(SHELL_EVENTS.approval, (payload) => {
    try {
      const { approval_id, approved } = parseApprovalDecision(payload);
      decide.mutate({ id: approval_id, approved });
    } catch (error) {
      reportShellFailure("a decision from a notification could not be read", error);
    }
  });

  return null;
}
