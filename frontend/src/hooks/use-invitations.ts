"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type {
  Invitation,
  InvitationCreated,
  NewInviteLink,
  InvitationList,
  InviteMemberInput,
} from "@/types";

export function useInvitations(orgId: string) {
  const queryClient = useQueryClient();

  // React Query owns the list: cached per-org, deduped, no refetch storms.
  // Mutations patch the cache directly to keep the UI instant. The query stays
  // disabled until an orgId is provided (some consumers mount with "" to only
  // use acceptInvitation).
  const { data: invitations = [], isLoading } = useQuery({
    queryKey: qk.invitations.list(orgId),
    queryFn: async () => (await apiClient.get<InvitationList>(`/orgs/${orgId}/invitations`)).items,
    enabled: !!orgId,
  });

  const writeCache = useCallback(
    (updater: (prev: Invitation[]) => Invitation[]) =>
      queryClient.setQueryData<Invitation[]>(qk.invitations.list(orgId), (prev = []) =>
        updater(prev),
      ),
    [queryClient, orgId],
  );

  // Kept for API compatibility: the list auto-fetches on mount; this forces a
  // background refresh.
  const fetchInvitations = useCallback(() => {
    if (!orgId) return;
    queryClient.invalidateQueries({ queryKey: qk.invitations.list(orgId) });
  }, [queryClient, orgId]);

  const invite = useCallback(
    async (input: InviteMemberInput): Promise<Invitation | null> => {
      try {
        const created = await apiClient.post<InvitationCreated>(
          `/orgs/${orgId}/invitations`,
          input,
        );
        // The token is stripped before the invitation reaches the cache. It is
        // a bearer credential, it is already on its way to the invitee by
        // email, and this cache backs the list rendered on the members page -
        // nothing here has a use for it, so nothing here keeps it.
        const { invitation_token: _token, ...invitation } = created;
        writeCache((prev) => [invitation, ...prev]);
        toast.success(`Invitation sent to ${input.email}`);
        return invitation;
      } catch {
        toast.error("Failed to send invitation");
        return null;
      }
    },
    [orgId, writeCache],
  );

  // By id, under the organization. The backend also revokes by token, but that
  // route is the invitee's - they have no id and no org - and putting a live
  // credential in the URL of an authenticated admin action would only write it
  // into server logs and browser history.
  const revokeInvitation = useCallback(
    async (invitationId: string) => {
      try {
        await apiClient.delete(`/orgs/${orgId}/invitations/${invitationId}`);
        writeCache((prev) => prev.filter((i) => i.id !== invitationId));
        toast.success("Invitation revoked");
      } catch {
        toast.error("Failed to revoke invitation");
      }
    },
    [orgId, writeCache],
  );

  // POST /invitations/<token> *is* the accept - the proxy route maps it onto the
  // backend's /accept. Posting to `/invitations/<token>/accept` from here hit no
  // route at all and came back as the 404 page; because the failure was
  // swallowed below, the accept screen then announced "You joined the
  // organization!" to people who had joined nothing. The error is rethrown so
  // that screen's error branch is reachable at all.
  const acceptInvitation = useCallback(async (token: string) => {
    try {
      await apiClient.post(`/invitations/${token}`);
      toast.success("Joined organization!");
    } catch (error) {
      toast.error("Failed to accept invitation");
      throw error;
    }
  }, []);

  /**
   * Mint a shareable link, and hand the URL back once.
   *
   * Unlike `invite`, the token *is* returned to the caller: a link nobody can
   * copy is a link that does nothing. It is still kept out of the cache - the
   * page shows it once, in the dialog that asked for it, and the listing that
   * cache backs carries no tokens for the same reason it never has.
   */
  const createLink = useCallback(
    async (input: NewInviteLink): Promise<string | null> => {
      try {
        const created = await apiClient.post<InvitationCreated>(
          `/orgs/${orgId}/invitations/link`,
          input,
        );
        const { invitation_token: token, ...invitation } = created;
        writeCache((prev) => [invitation, ...prev]);
        return `${window.location.origin}/invitations/${token}`;
      } catch {
        toast.error("Failed to create the link");
        return null;
      }
    },
    [orgId, writeCache],
  );

  return {
    invitations,
    isLoading,
    fetchInvitations,
    invite,
    createLink,
    revokeInvitation,
    acceptInvitation,
  };
}
