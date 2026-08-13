"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type {
  ResourceGrant,
  ResourceSharing,
  ShareInput,
  SharingResourceType,
  Visibility,
} from "@/types/sharing";

/**
 * Where each resource type's sharing endpoints are mounted.
 *
 * The backend generates the same four routes per type, so the prefix is the
 * only thing that differs between sharing an agent and sharing a collection.
 */
const SHARING_ROOT = {
  agent: "/agents",
  skill: "/skills",
  // `/kb`, which is where the template mounts knowledge bases and therefore
  // where the generated sharing routes land. This read `/knowledge-bases` - a
  // path the app has never served - and went unnoticed because the panel is
  // only mounted on agents so far.
  collection: "/kb",
  secret: "/secrets",
} as const satisfies Record<SharingResourceType, string>;

/**
 * Who reaches one resource: its owner, its visibility, and its explicit grants.
 *
 * Mutations invalidate rather than patch. Changing a visibility can change the
 * grant list the server reports back, and a level change is an upsert whose
 * result the client cannot derive - guessing is how a panel starts showing a
 * share that was never written.
 */
export function useSharing(resourceType: SharingResourceType, resourceId: string | null) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("sharing");
  const queryClient = useQueryClient();
  const base = `${SHARING_ROOT[resourceType]}/${resourceId}/sharing`;

  const { data, isLoading } = useQuery({
    queryKey: qk.sharing.detail(resourceType, resourceId ?? ""),
    queryFn: () => apiClient.get<ResourceSharing>(base),
    enabled: !!resourceId,
  });

  const invalidate = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: qk.sharing.detail(resourceType, resourceId ?? ""),
      }),
    [queryClient, resourceType, resourceId],
  );

  const share = useMutation({
    mutationFn: (input: ShareInput) => apiClient.put<ResourceGrant>(`${base}/grants`, input),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("sharingUpdated"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const revoke = useMutation({
    mutationFn: (subjectUserId: string) =>
      apiClient.delete<void>(`${base}/grants/${subjectUserId}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("accessRemoved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setVisibility = useMutation({
    mutationFn: (visibility: Visibility) =>
      apiClient.patch<ResourceSharing>(`${base}/visibility`, { visibility }),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("visibilityUpdated"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return { sharing: data, isLoading, share, revoke, setVisibility };
}
