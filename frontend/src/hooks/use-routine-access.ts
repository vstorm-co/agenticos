"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { routineAccessApi, type RoutineAccessUpdate } from "@/lib/routine-access-api";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";

/** A save refused because the routine, its sources or its tools changed since the read. */
export function isStaleReview(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

/**
 * A routine's access review: its sources and a setting for each tool.
 *
 * Read again on every opening rather than from the console's cache: publishing,
 * a rollback, an edited skill or a reconnected account all change what the
 * routine reaches - more writers than any one invalidation list keeps up with.
 */
export function useRoutineAccess(agentId: string, triggerId: string) {
  const client = useQueryClient();
  const t = useTranslations("errors");
  const key = qk.triggers.access(agentId, triggerId);
  const query = useQuery({
    queryKey: key,
    queryFn: () => routineAccessApi.get(agentId, triggerId),
    staleTime: 0,
  });
  const save = useMutation({
    mutationFn: (update: RoutineAccessUpdate) =>
      routineAccessApi.replace(agentId, triggerId, update),
    onSuccess: (data) => {
      client.setQueryData(key, data);
      // The routine lists and their readiness both sit under this prefix.
      void client.invalidateQueries({ queryKey: qk.triggers.all() });
    },
    onError: (error) => {
      // A stale review is explained in the dialog, beside the refreshed one.
      if (!isStaleReview(error)) toast.error(getErrorMessage(error, t));
      void client.invalidateQueries({ queryKey: key });
    },
  });
  return { ...query, save };
}

/**
 * Whether a routine's stored review no longer admits its next run - after an edit
 * to its prompt, who it runs as or where it delivers. Asked only of its creator,
 * the one caller the review answers.
 *
 * A failed check answers false: the edit itself is saved, and the routine's
 * readiness blockers say the same thing on its row.
 */
export function useRoutineAccessCheck() {
  const client = useQueryClient();
  return async (agentId: string, triggerId: string): Promise<boolean> => {
    try {
      const review = await client.fetchQuery({
        queryKey: qk.triggers.access(agentId, triggerId),
        queryFn: () => routineAccessApi.get(agentId, triggerId),
        staleTime: 0,
      });
      return !review.current;
    } catch {
      return false;
    }
  };
}
