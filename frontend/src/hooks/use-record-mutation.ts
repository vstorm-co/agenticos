"use client";

import { useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ApiError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { createRecord, deleteRecord, updateRecord } from "@/lib/tables-api";
import type { RecordCreate, RecordUpdate } from "@/types/tables";

/** Whether a failed write lost to a stale `expected_revision` (409). */
export function isRevisionConflict(error: unknown): boolean {
  return error instanceof ApiError && error.code === "REVISION_CONFLICT";
}

/**
 * The one create/update/delete mutation every cell editor, the record-detail
 * sheet and the kanban drag use, so conflict handling lives in one place.
 *
 * A stale revision (409) is never toasted here: the caller - a cell, a sheet
 * field, a dragged card - shows it inline with the local edit still visible and
 * a retry/discard action, per the acceptance criterion that a refused write
 * must not lose what the user typed or dragged. Every other failure toasts,
 * the same as any other mutation in this codebase.
 */
export function useRecordMutation(tableId: string) {
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const invalidate = useCallback(async () => {
    const queryKey = qk.tables.detail(tableId);
    // The prefix ["tables", tableId] also covers `records(tableId, ...)` for
    // every query any view or lane fetched it under, so one invalidation
    // refreshes the grid, every kanban lane and the list view together.
    await queryClient.cancelQueries({ queryKey });
    await queryClient.invalidateQueries({ queryKey });
  }, [queryClient, tableId]);

  const create = useMutation({
    mutationFn: (data: RecordCreate) => createRecord(tableId, data),
    onSuccess: () => invalidate(),
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const update = useMutation({
    mutationFn: ({ recordId, data }: { recordId: string; data: RecordUpdate }) =>
      updateRecord(tableId, recordId, data),
    onSuccess: () => invalidate(),
    onError: (error) => {
      if (!isRevisionConflict(error)) toast.error(getErrorMessage(error, tErrors));
    },
  });

  const remove = useMutation({
    mutationFn: ({ recordId, expectedRevision }: { recordId: string; expectedRevision: number }) =>
      deleteRecord(tableId, recordId, expectedRevision),
    onSuccess: () => invalidate(),
    onError: (error) => {
      if (!isRevisionConflict(error)) toast.error(getErrorMessage(error, tErrors));
    },
  });

  return { create, update, remove };
}
