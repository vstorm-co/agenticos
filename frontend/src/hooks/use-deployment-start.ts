"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import {
  readDeploymentOnboarding,
  saveDeploymentOnboarding,
  type StartScopeUpdate,
} from "@/lib/onboarding-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";

/** The deployment exists before its first organization; no fabricated tenant is needed. */
export function useDeploymentStart(enabled = true) {
  const user = useAuthStore((state) => state.user);
  const organization = useOrgStore((state) => state.activeOrgId);
  const errors = useTranslations("errors");
  const client = useQueryClient();
  const userId = user?.id;
  const allowed = enabled && !!userId && user?.is_app_admin === true && organization === null;
  const key = qk.onboarding.deployment(userId ?? "");
  const state = useQuery({
    queryKey: key,
    queryFn: readDeploymentOnboarding,
    enabled: allowed,
    staleTime: 10_000,
    retryOnMount: false,
    refetchOnWindowFocus: "always",
    refetchInterval: (query) => (query.state.data?.active_scope === "deployment" ? 10_000 : false),
  });
  const save = useMutation({
    mutationKey: [...key, "save"],
    scope: { id: `onboarding-deployment:${userId}` },
    mutationFn: async (write: { data: StartScopeUpdate; userId: string | undefined }) => {
      const current = useAuthStore.getState().user;
      if (
        !allowed ||
        current?.id !== write.userId ||
        current?.is_app_admin !== true ||
        useOrgStore.getState().activeOrgId !== null
      )
        throw new Error(errors("sessionExpired"));
      return {
        userId: write.userId,
        key: qk.onboarding.deployment(write.userId ?? ""),
        data: await saveDeploymentOnboarding(write.data),
      };
    },
    onSuccess: async (saved) => {
      const current = useAuthStore.getState().user;
      if (
        current?.id !== saved.userId ||
        current?.is_app_admin !== true ||
        useOrgStore.getState().activeOrgId !== null
      )
        return;
      client.setQueryData(saved.key, saved.data);
      await client.invalidateQueries({ queryKey: qk.onboarding.all() });
    },
    onError: () => client.invalidateQueries({ queryKey: key }),
  });
  return {
    ...state,
    allowed,
    save: {
      ...save,
      mutate: (data: StartScopeUpdate, options?: Parameters<typeof save.mutate>[1]) =>
        save.mutate({ data, userId }, options),
      mutateAsync: (data: StartScopeUpdate, options?: Parameters<typeof save.mutateAsync>[1]) =>
        save.mutateAsync({ data, userId }, options),
    },
  };
}
