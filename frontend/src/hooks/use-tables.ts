"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  archiveTable,
  createTable,
  getTable,
  listTables,
  updateSchema,
  updateTable,
  type TableListQuery,
} from "@/lib/tables-api";
import type { SchemaUpdate, TableCreate, TableUpdate } from "@/types/tables";

/**
 * The tables catalog: searched and paged on the server, like `useSkills`.
 *
 * An organization's tables grow without bound, so the client never assumes it
 * holds them all - `total` is the count before paging.
 */
export function useTables(query: TableListQuery = {}) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.tables");
  const queryClient = useQueryClient();
  const normalized: Required<TableListQuery> = {
    search: query.search ?? "",
    includeArchived: query.includeArchived ?? false,
    sort: query.sort ?? "name",
    skip: query.skip ?? 0,
    limit: query.limit ?? 50,
  };

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: qk.tables.list(normalized),
    queryFn: () => listTables(normalized),
    placeholderData: (previous) => previous,
  });

  const invalidate = useCallback(async () => {
    await queryClient.cancelQueries({ queryKey: qk.tables.all() });
    await queryClient.invalidateQueries({ queryKey: qk.tables.all() });
  }, [queryClient]);

  // No `onError`: a create can fail on a taken name, which the dialog still on
  // screen shows beside the input, the same reason `useSkills.create` has none.
  const create = useMutation({
    mutationFn: (data: TableCreate) => createTable(data),
    onSuccess: async (table) => {
      await invalidate();
      toast.success(t("created", { name: table.name }));
    },
  });

  const archive = useMutation({
    mutationFn: (tableId: string) => archiveTable(tableId),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("archived"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    tables: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    isFetching,
    error,
    refetch,
    create,
    archive,
  };
}

/** One table, with the columns of its current schema. */
export function useTable(tableId: string | null) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.tables");
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.tables.detail(tableId ?? ""),
    queryFn: () => getTable(tableId as string),
    enabled: !!tableId,
  });

  const invalidate = useCallback(async () => {
    if (!tableId) return;
    await queryClient.cancelQueries({ queryKey: qk.tables.detail(tableId) });
    await queryClient.invalidateQueries({ queryKey: qk.tables.detail(tableId) });
    await queryClient.invalidateQueries({ queryKey: qk.tables.all() });
  }, [queryClient, tableId]);

  const update = useMutation({
    mutationFn: (changes: TableUpdate) => updateTable(tableId as string, changes),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("saved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  // No `onError`: a schema conflict or an archived-column refusal is something
  // the schema editor dialog itself shows, field by field, not a toast.
  const changeSchema = useMutation({
    mutationFn: (data: SchemaUpdate) => updateSchema(tableId as string, data),
    onSuccess: async () => {
      await invalidate();
      await queryClient.invalidateQueries({ queryKey: qk.tables.schemaVersions(tableId ?? "") });
      toast.success(t("schemaSaved"));
    },
  });

  return { table: data, isLoading, error, refetch, update, changeSchema, invalidate };
}
