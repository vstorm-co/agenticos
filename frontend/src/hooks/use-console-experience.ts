"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useAuthStore, useOrgStore } from "@/stores";
import { useTenantId } from "@/hooks/use-organizations";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/api-error";
import {
  DEFAULT_CHAT_HOME,
  readConsoleExperience,
  saveConsoleExperience,
  type ConsoleExperienceChanges,
} from "@/lib/console-experience-api";

/** Membership-owned preferences never seed or optimistically alter another workspace. */
export function useConsoleExperience() {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const organizationId = useTenantId();
  const client = useQueryClient();
  const tErrors = useTranslations("errors");
  const key = qk.consoleExperience.member(organizationId, userId);
  const query = useQuery({
    queryKey: key,
    enabled: userId !== null && organizationId !== null,
    queryFn: () => {
      if (!organizationId || useAuthStore.getState().user?.id !== userId)
        throw new Error(tErrors("sessionExpired"));
      return readConsoleExperience(organizationId);
    },
    staleTime: 5000,
    refetchInterval: 10000,
  });
  const mutation = useMutation({
    scope: { id: `console-experience-${organizationId}-${userId}` },
    mutationFn: ({
      changes,
      ownerOrg,
      ownerUser,
    }: {
      changes: ConsoleExperienceChanges;
      ownerOrg: string | null;
      ownerUser: string | null;
    }) => {
      if (
        !ownerOrg ||
        useAuthStore.getState().user?.id !== ownerUser ||
        (useOrgStore.getState().activeOrgId !== null &&
          useOrgStore.getState().activeOrgId !== ownerOrg)
      )
        throw new Error(tErrors("sessionExpired"));
      return saveConsoleExperience(ownerOrg, changes);
    },
    onSuccess: (data, { ownerOrg, ownerUser }) =>
      client.setQueryData(qk.consoleExperience.member(ownerOrg, ownerUser), data),
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
  const save = {
    ...mutation,
    mutate: (changes: ConsoleExperienceChanges, onSaved?: () => void) =>
      mutation.mutate(
        { changes, ownerOrg: organizationId, ownerUser: userId },
        { onSuccess: onSaved },
      ),
    mutateAsync: (changes: ConsoleExperienceChanges) =>
      mutation.mutateAsync({ changes, ownerOrg: organizationId, ownerUser: userId }),
  };
  return {
    ...query,
    organizationId,
    userId,
    effective: query.data?.effective ?? DEFAULT_CHAT_HOME,
    save,
  };
}
