"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import {
  addGroupMember,
  createGroup,
  deleteGroup,
  listGroupMembers,
  listGroups,
  removeGroupMember,
  updateGroup,
} from "@/lib/groups-api";
import { qk } from "@/lib/query-keys";
import type { GroupCreate, GroupUpdate } from "@/types/groups";

/**
 * Invalidates one organization's groups, and with them every group's member
 * list, which sits beneath the same key: adding somebody to a group moves the
 * list's member count as well as the group's own rows.
 */
function useInvalidateGroups(orgId: string) {
  const queryClient = useQueryClient();
  return useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.organizations.groups(orgId) }),
    [queryClient, orgId],
  );
}

/**
 * One organization's groups, read and changed.
 *
 * Any member may read them - a group is what somebody shares with, so the
 * sharing picker needs the list whoever is sharing. Changing one takes
 * `members:manage`, which the pages decide before rendering the control.
 *
 * `create` and `update` report no failure of their own: the dialog that calls
 * them shows a taken name under the field it came from (`submitFailure`), and a
 * toast on top of that would say it twice.
 */
export function useGroups(orgId: string) {
  const t = useTranslations("groups");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const invalidate = useInvalidateGroups(orgId);

  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: qk.organizations.groups(orgId),
    queryFn: () => listGroups(orgId),
    enabled: !!orgId,
  });

  const create = useMutation({
    mutationFn: (input: GroupCreate) => createGroup(orgId, input),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("created"));
    },
  });

  const update = useMutation({
    mutationFn: ({ groupId, input }: { groupId: string; input: GroupUpdate }) =>
      updateGroup(orgId, groupId, input),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("saved"));
    },
  });

  const remove = useMutation({
    mutationFn: (groupId: string) => deleteGroup(orgId, groupId),
    onSuccess: async () => {
      // The server deletes the grants made to the group and the directory
      // mappings naming it in the same transaction, so both are stale now too.
      await Promise.all([
        invalidate(),
        queryClient.invalidateQueries({ queryKey: qk.organizations.directoryMappings(orgId) }),
        queryClient.invalidateQueries({ queryKey: qk.sharing.all() }),
      ]);
      toast.success(t("deleted"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  return { groups: data?.items ?? [], isLoading, isFetching, error, create, update, remove };
}

/** Who is in one group, and adding or removing somebody by hand. */
export function useGroupMembers(orgId: string, groupId: string) {
  const t = useTranslations("groups");
  const tErrors = useTranslations("errors");
  const invalidate = useInvalidateGroups(orgId);

  const { data, isLoading, error } = useQuery({
    queryKey: qk.organizations.groupMembers(orgId, groupId),
    queryFn: () => listGroupMembers(orgId, groupId),
  });

  const add = useMutation({
    mutationFn: (userId: string) => addGroupMember(orgId, groupId, userId),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("memberAdded"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  const remove = useMutation({
    mutationFn: (userId: string) => removeGroupMember(orgId, groupId, userId),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("memberRemoved"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  return { members: data?.items ?? [], isLoading, error, add, remove };
}
