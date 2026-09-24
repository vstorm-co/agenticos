"use client";

import { useCallback, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ApiError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { createRecord, deleteRecord, getRecord, updateRecord } from "@/lib/tables-api";
import type { RecordCreate, RecordRead, RecordUpdate } from "@/types/tables";

/** Whether a failed write lost to a stale `expected_revision` (409). */
export function isRevisionConflict(error: unknown): boolean {
  return error instanceof ApiError && error.code === "REVISION_CONFLICT";
}

/** Whether a failed read or write found no record: deleted meanwhile, or no longer reachable. */
export function isRecordGone(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
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
 *
 * `commit` is how a surface writes a record's values; `update` stays for its
 * pending state. `fetchRecord` reads one record fresh, for "reload and reapply".
 */
export function useRecordMutation(tableId: string) {
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const invalidate = useCallback(async () => {
    // Every records query any view or lane fetched, and nothing else: a record
    // write changes neither the table, nor its views, nor its schema versions.
    const queryKey = qk.tables.recordsAll(tableId);
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

  // Per record: the tail of its write chain, and the newest revision a write
  // of ours has been answered with.
  const tails = useRef(new Map<string, Promise<void>>());
  const revisions = useRef(new Map<string, number>());
  const { mutateAsync } = update;

  /**
   * Write `values` to one record, after every earlier `commit` to the same
   * record has settled, against the newest revision known for it.
   *
   * Two writes to one record started within one round trip - a text field
   * committing on blur as the click that caused the blur commits a switch - would
   * otherwise both carry the revision the caller last saw, and the server refuses
   * whichever lands second against the user's own first write. Chaining makes
   * the second wait for the first and take its answer's revision. The returned
   * promise is this call's own result: a caller handles success and conflict on
   * it, never through `mutate` callbacks, which TanStack drops for every call a
   * later one on the same observer supersedes.
   */
  const commit = useCallback(
    (record: Pick<RecordRead, "id" | "revision">, values: RecordUpdate["values"]) => {
      const previous = tails.current.get(record.id) ?? Promise.resolve();
      const result = previous.then(async () => {
        // Revisions only grow, so the larger of the caller's and our own last
        // answer is the newest either has seen.
        const known = revisions.current.get(record.id) ?? record.revision;
        const updated = await mutateAsync({
          recordId: record.id,
          data: { expected_revision: Math.max(known, record.revision), values },
        });
        revisions.current.set(record.id, updated.revision);
        return updated;
      });
      // A refused write must not wedge every later write to the same record.
      const tail = result.then(
        () => undefined,
        () => undefined,
      );
      tails.current.set(record.id, tail);
      void tail.then(() => {
        if (tails.current.get(record.id) === tail) tails.current.delete(record.id);
      });
      return result;
    },
    [mutateAsync],
  );

  /** One record as the server holds it now, through the query cache rather than around it. */
  const fetchRecord = useCallback(
    (recordId: string) =>
      queryClient.fetchQuery({
        queryKey: qk.tables.record(tableId, recordId),
        queryFn: () => getRecord(tableId, recordId),
        staleTime: 0,
      }),
    [queryClient, tableId],
  );

  return { create, update, remove, commit, fetchRecord, invalidate };
}
