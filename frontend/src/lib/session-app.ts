/**
 * Tell the server which AgenticOS app this console is loaded in (#2305,
 * #2097), so the account's sessions list names the app and its version rather
 * than the webview's browser engine - and Disconnect there means the app.
 */

import { apiClient } from "@/lib/api-client";
import type { ShellInfo } from "@/lib/desktop/shell";

export async function recordSessionApp(shell: ShellInfo): Promise<void> {
  await apiClient.put("/sessions/current/app", {
    platform: shell.platform,
    version: shell.version,
  });
}
