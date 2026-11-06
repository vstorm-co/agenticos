"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listNotificationRoutes,
  replaceNotificationRoute,
} from "@/lib/notification-preferences-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores/org-store";

export function useNotificationRoutes() {
  const organizationId = useOrgStore((state) => state.activeOrgId);
  const queryClient = useQueryClient();
  const key = qk.notifications.destinations(organizationId);
  const query = useQuery({
    queryKey: key,
    queryFn: listNotificationRoutes,
    enabled: organizationId !== null,
  });
  const mutation = useMutation({
    mutationFn: replaceNotificationRoute,
    onSettled: async () => {
      // A change of organization while saving cannot seed a different tenant's cache.
      await queryClient.invalidateQueries({ queryKey: key });
    },
  });
  return {
    ...query,
    isLoading: query.isPending,
    replace: mutation.mutateAsync,
    isSaving: mutation.isPending,
  };
}
