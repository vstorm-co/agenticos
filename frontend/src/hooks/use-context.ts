"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { PAGE_SIZE } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { ContextFile, ContextFileList, ContextMode } from "@/types/providers";

export interface NewContextFile {
  name: string;
  description: string | null;
  content: string;
  format: string;
  mode: ContextMode;
}

/** How the server may order a listing. */
export type ContextSort = "name" | "updated";

/** Which slice of the organization's context files to ask for. */
export interface ContextQuery {
  /** Matched against name and description, by the database. */
  search?: string;
  sort?: ContextSort;
  skip?: number;
  limit?: number;
}

/**
 * An organization's standing context files.
 *
 * The list returns names, modes and sizes only - the bodies can be long, and
 * the picker never needs them. Searching and paging happen on the server, so
 * `total` is the count before paging, which tells a caller whether the slice it
 * got is the whole set.
 */
export function useContextFiles({
  search = "",
  sort = "name",
  skip = 0,
  limit = PAGE_SIZE,
}: ContextQuery = {}) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("context");
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.context.list({ search, sort, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      params.set("sort", sort);
      params.set("skip", String(skip));
      params.set("limit", String(limit));
      return apiClient.get<ContextFileList>(`/context?${params}`);
    },
    placeholderData: (previous) => previous,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.context.all() }),
    [queryClient],
  );

  // No `onError`, like `useSkills.create`: every way this fails - the name is
  // taken, a field is too long - is something the reader fixes in the dialog
  // still on screen, so the dialog owns where to say it.
  const create = useMutation({
    mutationFn: (file: NewContextFile) => apiClient.post<ContextFile>("/context", file),
    onSuccess: async (file) => {
      await invalidate();
      toast.success(t("created", { name: file.name }));
    },
  });

  const update = useMutation({
    mutationFn: ({
      id,
      ...changes
    }: { id: string } & Partial<NewContextFile & { enabled: boolean }>) =>
      apiClient.patch<ContextFile>(`/context/${id}`, changes),
    onSuccess: async () => {
      await invalidate();
      // Files are bound by reference, so an edit reaches every agent at once.
      toast.success(t("savedAgentsCurrent"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/context/${id}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("deleted"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    files: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    refetch,
    create,
    update,
    remove,
  };
}

/** What the editor may change on a file that already exists - never its name. */
export interface ContextEdit {
  description: string | null;
  content: string;
  format: string;
  mode: ContextMode;
  enabled: boolean;
}

/**
 * One context file, body included.
 *
 * Separate from the list because the list omits `content` - the picker never
 * needs a body and the editor cannot work without one. The name is not editable:
 * it is the handle a person and the `link` tool both use, and the API refuses to
 * change it.
 */
export function useContextFile(fileId: string | null) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("context");
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: qk.context.detail(fileId ?? ""),
    queryFn: () => apiClient.get<ContextFile>(`/context/${fileId}`),
    enabled: fileId !== null,
  });

  const save = useMutation({
    mutationFn: (edit: ContextEdit) => apiClient.patch<ContextFile>(`/context/${fileId}`, edit),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.context.all() });
      // Agents bind to the file, not a version of it, so this is already live.
      toast.success(t("savedAgentsCurrent"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return { file: data, isLoading, save };
}
