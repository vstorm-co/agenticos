"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { updateTable } from "@/lib/tables-api";
import { createView, deleteView, listViews, updateView } from "@/lib/table-views-api";
import type { TableViewCreate, TableViewUpdate, ViewKind } from "@/types/tables";

/** The caller's own saved views plus the shared ones, under one table. */
export function useTableViews(tableId: string | null, kind?: ViewKind) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.tables.views");
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.tables.viewsOfKind(tableId ?? "", kind ?? null),
    queryFn: () => listViews(tableId as string, kind),
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

  return {
    views: data?.items ?? [],
    isLoading,
    error,
    refetch,
    create,
    update,
    remove,
  };
}

/** Choose a shared saved view for everyone opening this table without a URL override. */
export function useTableDefaultView(tableId: string) {
  const client = useQueryClient();
  const t = useTranslations("pages.tables.views");
  const errors = useTranslations("errors");
  return useMutation({
    mutationFn: async ({
      view,
      kind,
      config,
      names,
    }: {
      view: import("@/types/tables").TableViewRead | null;
      kind: ViewKind;
      config: import("@/types/tables").TableViewConfig;
      names: string[];
    }) => {
      let selected = view?.can_manage ? view : null;
      if (selected?.can_manage)
        selected = await updateView(tableId, selected.id, { visibility: "shared", config });
      if (!selected) {
        const base = t("defaultName", { kind });
        let name = base;
        for (let suffix = 2; names.includes(name); suffix += 1) name = `${base} ${suffix}`;
        selected = await createView(tableId, { name, kind, visibility: "shared", config });
      }
      await updateTable(tableId, { default_view_id: selected.id });
      return selected;
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: qk.tables.views(tableId) });
      await client.invalidateQueries({ queryKey: qk.tables.detail(tableId) });
      await client.invalidateQueries({ queryKey: qk.tables.lists() });
      toast.success(t("defaultSaved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, errors)),
  });
}
