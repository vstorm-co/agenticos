/**
 * What, of the inbox and the approval queue, is news worth a native
 * notification - decided here, in pure functions, so the bridge only plumbs.
 */

import type { Notification } from "@/lib/notifications-api";
import { isConsolePath } from "@/lib/desktop/paths";
import type { ToolApproval } from "@/types/runs";

/** Approvals that are pending now and were not pending in the last look. */
export function newApprovals(
  seen: ReadonlySet<string>,
  approvals: readonly ToolApproval[],
): ToolApproval[] {
  return approvals.filter((approval) => approval.status === "pending" && !seen.has(approval.id));
}

/**
 * Inbox rows created after the newest one already seen, oldest first, unread
 * only - every unread row when none had been seen, an empty inbox at the first
 * look. An approval request is left out: the approval queue notifies it, with
 * the buttons to decide it.
 */
export function newNotifications(
  since: string | null,
  rows: readonly Notification[],
): Notification[] {
  return rows
    .filter((row) => (since === null || row.created_at > since) && row.read_at === null)
    .filter((row) => row.event_type !== "approval_requested")
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

/** The newest creation time among the rows, or what was known before. */
export function newestOf(since: string | null, rows: readonly Notification[]): string | null {
  return rows.reduce<string | null>(
    (newest, row) => (newest === null || row.created_at > newest ? row.created_at : newest),
    since,
  );
}

const ARGUMENT_PREVIEW = 160;

/**
 * What a tool call would do, short enough for a notification: the arguments as
 * `name: value` pairs. Approving a tool name without its arguments is a rubber
 * stamp, so they are always in the body, cut rather than left out.
 */
export function argumentsPreview(args: Record<string, unknown>): string {
  const text = Object.entries(args)
    .map(([name, value]) => `${name}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(", ");
  return text.length > ARGUMENT_PREVIEW ? `${text.slice(0, ARGUMENT_PREVIEW - 1)}…` : text;
}

/** Where a notification row opens: its own page when it names one on the console, the inbox otherwise. */
export function notificationPath(row: Notification): string {
  return row.context_url && isConsolePath(row.context_url) ? row.context_url : "/dashboard";
}
