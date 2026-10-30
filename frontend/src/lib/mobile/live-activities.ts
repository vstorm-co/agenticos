/**
 * Live activities: what the phone app draws outside itself while an agent works
 * or waits - the Dynamic Island and the lock screen on iOS, an ongoing
 * notification on Android (`mobile/src-tauri/src/live.rs`).
 *
 * The console decides what is live, from reads it already makes, and tells the
 * app; the app draws it. A button on one comes back to the console through
 * `takeActivityAction`, and the console acts on it with its own session.
 */

import { isConsolePath } from "@/lib/desktop/paths";
import { invokeShell, ShellError } from "@/lib/desktop/shell";
import type { ComposerIntent } from "@/stores/composer-intent-store";

/** A run going, an approval or a question waiting on the person, or a voice call. */
export type LiveActivityKind = "run" | "approval" | "question" | "call";

/** One live activity, in the shape `live.rs` reads. */
export interface LiveActivity {
  /** Stable for what it is about - `run:<id>`, `approval:<id>` - so showing it again updates it. */
  id: string;
  kind: LiveActivityKind;
  title: string;
  body: string;
  /** The console page a tap on it opens. */
  path: string;
  /** Milliseconds since the epoch, for a clock the phone counts up on its own. */
  startedAt?: number;
  approvalId?: string;
  approveLabel?: string;
  rejectLabel?: string;
}

/** What a live activity's button, or a shortcut, asked of the console. */
export type ActivityAsk =
  | { kind: "open"; path: string }
  | { kind: "decide"; approval_id: string; approved: boolean }
  | { kind: "start"; mode: ComposerIntent };

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** The app's answer to `take_activity_action`: nothing waiting, or one ask. */
export function parseActivityAsk(value: unknown): ActivityAsk | null {
  if (value === null) return null;
  if (isRecord(value)) {
    const { kind, path, approval_id, approved, mode } = value;
    if (kind === "open" && typeof path === "string" && isConsolePath(path)) {
      return { kind, path };
    }
    if (kind === "decide" && typeof approval_id === "string" && typeof approved === "boolean") {
      return { kind, approval_id, approved };
    }
    if (kind === "start" && (mode === "call" || mode === "dictate")) {
      return { kind, mode };
    }
  }
  throw new ShellError("malformed", "an activity's action");
}

export async function showActivity(activity: LiveActivity): Promise<void> {
  await invokeShell("show_activity", { activity });
}

export async function endActivity(id: string): Promise<void> {
  await invokeShell("end_activity", { id });
}

export async function takeActivityAction(): Promise<ActivityAsk | null> {
  return parseActivityAsk(await invokeShell("take_activity_action"));
}

/**
 * What to tell the app, given what it was last told (`shown`, an activity's id
 * to its last content): the activities that are new or changed, and the ids of
 * those that are over.
 *
 * Showing an unchanged activity again would be harmless on the lock screen and
 * a nuisance in the battery figures - every poll would redraw every one.
 */
export function planActivities(
  shown: ReadonlyMap<string, string>,
  next: readonly LiveActivity[],
): { show: LiveActivity[]; end: string[] } {
  const live = new Set(next.map((activity) => activity.id));
  return {
    show: next.filter((activity) => shown.get(activity.id) !== JSON.stringify(activity)),
    end: [...shown.keys()].filter((id) => !live.has(id)),
  };
}
