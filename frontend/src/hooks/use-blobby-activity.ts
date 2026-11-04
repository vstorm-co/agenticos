"use client";

import { useAssistantSignals } from "@/hooks/use-assistant-signals";
import { useUnreadNotificationCount } from "@/hooks/use-notifications";
import { useRuns } from "@/hooks/use-runs";
import { activityOf, type Activity } from "@/lib/desktop/blobby-engine";
import { useAuthStore } from "@/stores";

/** How often the person's running runs are counted; a run is long enough for this. */
const RUNNING_POLL_MS = 15_000;

/**
 * What the person's agents are doing, as blobby should mention it: an approval
 * waiting, something unread in the inbox, or their own runs in flight.
 *
 * Each read is one a console page already makes - the Architect's signals, the
 * bell's count, the runs list narrowed to this person's running ones - so blobby
 * asks nothing the console does not, and is refused nothing the console is not.
 */
export function useBlobbyActivity(enabled: boolean): Activity {
  const userId = useAuthStore((state) => state.user?.id);
  const { pendingApprovals } = useAssistantSignals();
  const unread = useUnreadNotificationCount(enabled);
  const { total: running } = useRuns(undefined, {
    enabled: enabled && userId !== undefined,
    statuses: ["running"],
    userId,
    refetchIntervalMs: RUNNING_POLL_MS,
  });
  if (!enabled) return { kind: "quiet" };
  return activityOf({ approvals: pendingApprovals, unread: unread.count, running });
}
