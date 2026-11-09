"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

export interface ReceivedInvitation {
  id: string;
  organization_id: string;
  organization_name: string;
  organization_has_avatar: boolean;
  organization_avatar_color: number | null;
  role: string;
  expires_at: string;
}

export function useReceivedInvitations(enabled: boolean) {
  const userId = useAuthStore((state) => state.user?.id);
  const client = useQueryClient();
  const key = qk.invitations.received(userId ?? "");
  const query = useQuery({
    queryKey: key,
    queryFn: () => apiClient.get<ReceivedInvitation[]>("/invitations/received"),
    enabled: enabled && !!userId,
    staleTime: 0,
    refetchOnWindowFocus: true,
    refetchInterval: 60_000,
  });
  const accept = useMutation({
    mutationFn: (id: string) =>
      apiClient.post<{ organization_id: string }>(
        `/invitations/received/${encodeURIComponent(id)}/accept`,
      ),
    onSuccess: async (_result, id) => {
      client.setQueryData<ReceivedInvitation[]>(key, (old) =>
        old?.filter((item) => item.id !== id),
      );
      await client.invalidateQueries({ queryKey: qk.organizations.list() });
      await client.invalidateQueries({ queryKey: key });
    },
  });
  return { ...query, accept };
}
