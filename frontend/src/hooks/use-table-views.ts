"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { createView, deleteView, listViews, updateView } from "@/lib/table-views-api";
import type { TableViewCreate, TableViewUpdate, ViewKind } from "@/types/tables";

/** The caller's own saved views plus the shared ones, under one table. */
export function useTableViews(tableId: string | null, kind?: ViewKind) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.tables.views");
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.tables.views(tableId ?? ""),
    queryFn: () => listViews(tableId as string),
    enabled: !!tableId,
  });

  const invalidate = useCallback(async () => {
    if (!tableId) return;
    await queryClient.cancelQueries({ queryKey: qk.tables.views(tableId) });
    await queryClient.invalidateQueries({ queryKey: qk.tables.views(tableId) });
  }, [queryClient, tableId]);

  // No `onError` on create or update: the dialog still on screen shows the
  // failure - a taken name beside the input - the same reason
  // `useSkills.create` has none.
  const create = useMutation({
    mutationFn: (data: TableViewCreate) => createView(tableId as string, data),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("created"));
    },
  });

  const update = useMutation({
    mutationFn: ({ viewId, data }: { viewId: string; data: TableViewUpdate }) =>
      updateView(tableId as string, viewId, data),
    onSuccess: async () => {
      await invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: (viewId: string) => deleteView(tableId as string, viewId),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("deleted"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const items = data?.items ?? [];
  return {
    views: kind ? items.filter((view) => view.kind === kind) : items,
    isLoading,
    error,
    refetch,
    create,
    update,
    remove,
  };
}
