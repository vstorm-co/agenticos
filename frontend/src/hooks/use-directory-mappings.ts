"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import {
  createDirectoryMapping,
  deleteDirectoryMapping,
  listDirectoryMappings,
} from "@/lib/directory-api";
import { qk } from "@/lib/query-keys";
import type { DirectoryMappingCreate } from "@/types/directory";

/**
 * One organization's directory group mappings.
 *
 * `enabled` is the caller's `members:manage`: the list is refused without it, and
 * a page that asked anyway would render the refusal as an empty table - "no
 * mappings yet" and "you may not see them" being the same pixels.
 *
 * `create` reports no failure of its own, for the reason `useGroups` gives: the
 * dialog shows an already-mapped group under the field it came from.
 */
export function useDirectoryMappings(orgId: string, enabled: boolean) {
  const t = useTranslations("directory");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: qk.organizations.directoryMappings(orgId),
    queryFn: () => listDirectoryMappings(orgId),
    enabled,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.organizations.directoryMappings(orgId) }),
    [queryClient, orgId],
  );

  const create = useMutation({
    mutationFn: (input: DirectoryMappingCreate) => createDirectoryMapping(orgId, input),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("mappingAdded"));
    },
  });

  const remove = useMutation({
    mutationFn: (mappingId: string) => deleteDirectoryMapping(orgId, mappingId),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("mappingDeleted"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  return { mappings: data?.items ?? [], isLoading, error, create, remove };
}
