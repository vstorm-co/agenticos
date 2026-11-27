"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import {
  routineToolsApi,
  type RoutineToolOptions,
  type RoutineToolSetting,
} from "@/lib/routine-tools-api";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/api-error";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";

interface RoutineToolWrite {
  settings: RoutineToolSetting[];
  ownerId: string | null;
  orgId: string | null;
  key: ReturnType<typeof qk.triggers.toolSettings>;
}
interface RoutineToolReceipt {
  data: RoutineToolOptions;
  ownerId: string;
  orgId: string | null;
  key: ReturnType<typeof qk.triggers.toolSettings>;
}
interface RoutineToolsResult {
  data: RoutineToolOptions | undefined;
  error: Error | null;
  isLoading: boolean;
  refetch: () => Promise<void>;
  replace: { isPending: boolean; mutateAsync: (settings: RoutineToolSetting[]) => Promise<void> };
}

export function useRoutineTools(
  agentId: string,
  triggerId: string,
  { enabled = true } = {},
): RoutineToolsResult {
  const client = useQueryClient();
  const t = useTranslations("errors");
  const ownerId = useAuthStore((state) => state.sessionOwnerId ?? state.user?.id ?? null);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const key = qk.triggers.toolSettings(ownerId, orgId, agentId, triggerId);
  const query = useQuery({
    queryKey: key,
    queryFn: () => routineToolsApi.get(agentId, triggerId),
    enabled: enabled && ownerId !== null,
    staleTime: 0,
    retry: false,
  });
  const replace = useMutation({
    mutationFn: async (write: RoutineToolWrite): Promise<RoutineToolReceipt> => {
      const auth = useAuthStore.getState();
      const currentOwner = auth.sessionOwnerId ?? auth.user?.id ?? null;
      if (
        write.ownerId === null ||
        currentOwner !== write.ownerId ||
        useOrgStore.getState().activeOrgId !== write.orgId
      ) {
        throw new Error(t("sessionExpired"));
      }
      const data = await routineToolsApi.replace(agentId, triggerId, write.settings);
      return { data, ownerId: write.ownerId, orgId: write.orgId, key: write.key };
    },
    onSuccess: (result) => {
      const auth = useAuthStore.getState();
      if (
        (auth.sessionOwnerId ?? auth.user?.id ?? null) !== result.ownerId ||
        useOrgStore.getState().activeOrgId !== result.orgId
      )
        return;
      client.setQueryData(result.key, result.data);
      void client.invalidateQueries({ queryKey: qk.triggers.all() });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, t));
      void client.invalidateQueries({ queryKey: key });
    },
  });
  return {
    data: query.data,
    error: query.error,
    isLoading: query.isLoading,
    refetch: async () => {
      await query.refetch();
    },
    replace: {
      isPending: replace.isPending,
      mutateAsync: async (settings: RoutineToolSetting[]) => {
        await replace.mutateAsync({ settings, ownerId, orgId, key });
      },
    },
  };
}
