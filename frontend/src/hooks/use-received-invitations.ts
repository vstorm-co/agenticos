"use client";

import {
  useMutation,
  useInfiniteQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
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
  const proved = useAuthStore((state) => state.user?.email_verified === true);
  const email = useAuthStore((state) => state.user?.email ?? "");
  const key = [...qk.invitations.received(userId ?? ""), email, proved];
  const query = useInfiniteQuery({
    queryKey: key,
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      apiClient.get<ReceivedInvitation[]>("/invitations/received", {
        params: { skip: String(pageParam), limit: "50" },
      }),
    getNextPageParam: (page, pages) => (page.length === 50 ? pages.length * 50 : undefined),
    enabled: enabled && !!userId && proved,
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
      client.setQueryData<InfiniteData<ReceivedInvitation[]>>(key, (old) =>
        old
          ? { ...old, pages: old.pages.map((page) => page.filter((item) => item.id !== id)) }
          : old,
      );
      await client.invalidateQueries({ queryKey: qk.organizations.list() });
      await client.invalidateQueries({ queryKey: key });
    },
  });
  return { ...query, data: query.data?.pages.flat(), accept };
}
