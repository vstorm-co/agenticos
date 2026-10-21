/**
 * The phone app's home-screen widget (`mobile/src-tauri/src/widget.rs`): the
 * counts the console already reads, kept for the widget to show with the time
 * they were counted.
 */

import { invokeShell } from "@/lib/desktop/shell";

export interface Glance {
  /** Approvals waiting for this person's decision. */
  approvals: number;
  /** This person's own runs in flight. */
  running: number;
}

export async function updateWidget(glance: Glance): Promise<void> {
  await invokeShell("update_widget", { glance });
}
