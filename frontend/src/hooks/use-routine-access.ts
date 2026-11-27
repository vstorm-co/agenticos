"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { routineAccessApi, type RoutineAccessUpdate } from "@/lib/routine-access-api";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";

/** A save refused because the routine, its sources or its tools changed since the read. */
export function isStaleReview(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

function sessionOwner(): string | null {
  const auth = useAuthStore.getState();
  return auth.sessionOwnerId ?? auth.user?.id ?? null;
}

interface AccessWrite {
  update: RoutineAccessUpdate;
  key: ReturnType<typeof qk.triggers.access>;
  ownerId: string | null;
  orgId: string | null;
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
  const ownerId = useAuthStore((state) => state.sessionOwnerId ?? state.user?.id ?? null);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const key = qk.triggers.access(ownerId, orgId, agentId, triggerId);
  const query = useQuery({
    queryKey: key,
    queryFn: () => routineAccessApi.get(agentId, triggerId),
    enabled: ownerId !== null,
    staleTime: 0,
  });
  const mutation = useMutation({
    mutationFn: async (write: AccessWrite) => {
      // A save started for one session must not be sent as another.
      if (
        write.ownerId === null ||
        sessionOwner() !== write.ownerId ||
        useOrgStore.getState().activeOrgId !== write.orgId
      ) {
        throw new Error(t("sessionExpired"));
      }
      return routineAccessApi.replace(agentId, triggerId, write.update);
    },
    onSuccess: (data, write) => {
      // A late answer is not cached for whoever signed in meanwhile.
      if (sessionOwner() !== write.ownerId || useOrgStore.getState().activeOrgId !== write.orgId)
        return;
      client.setQueryData(write.key, data);
      // The routine lists and their readiness both sit under this prefix.
      void client.invalidateQueries({ queryKey: qk.triggers.all() });
    },
    onError: (error, write) => {
      // A stale review is explained in the dialog, beside the refreshed one.
      if (!isStaleReview(error)) toast.error(getErrorMessage(error, t));
      void client.invalidateQueries({ queryKey: write.key });
    },
  });
  const save = {
    isPending: mutation.isPending,
    error: mutation.error,
    mutateAsync: (update: RoutineAccessUpdate) =>
      mutation.mutateAsync({ update, key, ownerId, orgId }),
  };
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
        queryKey: qk.triggers.access(
          sessionOwner(),
          useOrgStore.getState().activeOrgId,
          agentId,
          triggerId,
        ),
        queryFn: () => routineAccessApi.get(agentId, triggerId),
        staleTime: 0,
      });
      return !review.current;
    } catch {
      return false;
    }
  };
}
