"use client";

import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { deleteRecord } from "@/lib/tables-api";
import { useTableViewStore } from "@/stores";
import type { RecordRead } from "@/types/tables";

import { isRevisionConflict } from "./use-record-mutation";

/** How long a delete can be undone before it is sent. */
export const UNDO_MS = 6000;

/**
 * Delete records with a short window to take it back.
 *
 * The records leave every view at once and a toast offers **Undo**; only when
 * the window closes is each delete sent, against the revision on screen, so a
 * record someone changed meanwhile is kept and said to be. A delete is hard on
 * the server - its history stays - so the undo is the not sending: nothing has
 * to be put back. Sent by the API directly rather than a component's mutation,
 * so leaving the page inside the window still deletes what was asked to be.
 */
export function useDeferredDelete(tableId: string) {
  const t = useTranslations("tables.grid");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const hide = useTableViewStore((state) => state.hide);
  const unhide = useTableViewStore((state) => state.unhide);

  return useCallback(
    (records: RecordRead[]) => {
      const ids = records.map((record) => record.id);
      hide(ids);

      const send = async () => {
        const results = await Promise.allSettled(
          records.map((record) => deleteRecord(tableId, record.id, record.revision)),
        );
        // Refetched first, so a deleted record is gone from the data before it
        // stops being hidden, and a kept one simply comes back.
        await queryClient.invalidateQueries({ queryKey: qk.tables.recordsAll(tableId) });
        unhide(ids);
        const failures = results.filter((result) => result.status === "rejected");
        const conflicts = failures.filter((result) => isRevisionConflict(result.reason));
        if (conflicts.length > 0) toast.error(t("deleteConflict", { count: conflicts.length }));
        const other = failures.find((result) => !isRevisionConflict(result.reason));
        if (other !== undefined) toast.error(getErrorMessage(other.reason, tErrors));
      };

      const timer = setTimeout(() => void send(), UNDO_MS);
      toast.success(t("deleted", { count: records.length }), {
        duration: UNDO_MS,
        action: {
          label: t("undo"),
          onClick: () => {
            clearTimeout(timer);
            unhide(ids);
          },
        },
      });
    },
    [hide, unhide, queryClient, tableId, t, tErrors],
  );
}
