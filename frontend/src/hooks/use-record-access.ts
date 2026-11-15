"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  getRecordAccess,
  revokeRecordGrant,
  setRecordGrant,
  setTableRowPolicy,
  type RecordGrantInput,
} from "@/lib/table-record-access-api";
import type { GrantSubject } from "@/types/sharing";
import type { RowPolicy } from "@/types/tables";

function useAccessInvalidation() {
  const queryClient = useQueryClient();
  const t = useTranslations("tables.access");
  const errors = useTranslations("errors");
  return {
    onSuccess: async () => {
      // Row grants also change linked labels and rollups in other open tables.
      await queryClient.cancelQueries({ queryKey: qk.tables.all() });
      await queryClient.invalidateQueries({ queryKey: qk.tables.all() });
      toast.success(t("saved"));
    },
    onError: (error: unknown) => toast.error(getErrorMessage(error, errors)),
  };
}

export function useRecordAccess(tableId: string, recordId: string | null) {
  const callbacks = useAccessInvalidation();
  const query = useQuery({
    queryKey: qk.tables.recordAccess(tableId, recordId ?? ""),
    queryFn: () => getRecordAccess(tableId, recordId!),
    enabled: recordId !== null,
  });
  const share = useMutation({
    mutationFn: (input: RecordGrantInput) => setRecordGrant(tableId, recordId!, input),
    ...callbacks,
  });
  const revoke = useMutation({
    mutationFn: (subject: GrantSubject) => revokeRecordGrant(tableId, recordId!, subject),
    ...callbacks,
  });
  return { ...query, share, revoke };
}

export function useTableRowPolicy(tableId: string) {
  const callbacks = useAccessInvalidation();
  return useMutation({
    mutationFn: (policy: RowPolicy) => setTableRowPolicy(tableId, policy),
    ...callbacks,
  });
}
