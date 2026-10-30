"use client";
import { useAuthStore } from "@/stores";
import { usePermissions } from "./use-permissions";
import { useRuns } from "./use-runs";
import { Perm } from "@/types/permissions";

/** One shared, account-filtered query for activity and notification context. */
export function useDesktopActiveRuns() {
  const user = useAuthStore((s) => s.user?.id);
  const { can } = usePermissions();
  return useRuns(undefined, {
    userId: user,
    statuses: ["running", "awaiting_answer", "awaiting_approval"],
    enabled: !!user && can(Perm.runsView),
    refetchIntervalMs: 5000,
    refetchInBackground: true,
  });
}
