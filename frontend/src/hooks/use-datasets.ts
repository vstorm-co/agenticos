"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { PAGE_SIZE } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";
import { qk } from "@/lib/query-keys";
import type {
  Dataset,
  DatasetCase,
  DatasetCaseContent,
  DatasetCaseList,
  DatasetFileFormat,
  DatasetList,
  DatasetSort,
  DatasetVersion,
  DatasetVersionList,
} from "@/types/datasets";

/** Which slice of the organization's datasets to ask for. */
export interface DatasetQuery {
  /** Matched against name and description, by the database. */
  search?: string;
  sort?: DatasetSort;
  skip?: number;
  limit?: number;
  /** False holds the request until it is needed, as a picker behind a checkbox is. */
  enabled?: boolean;
}

export interface NewDataset {
  name: string;
  description: string | null;
}

/**
 * The organization's datasets the caller may see.
 *
 * Each row says whether the caller may change it (`can_edit`), so a picker of
 * where to add a case can offer only the ones that would accept it.
 */
export function useDatasets({
  search = "",
  sort = "name",
  skip = 0,
  limit = PAGE_SIZE,
  enabled = true,
}: DatasetQuery = {}) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: qk.datasets.list({ search, sort, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      params.set("sort", sort);
      params.set("skip", String(skip));
      params.set("limit", String(limit));
      return apiClient.get<DatasetList>(`/datasets?${params}`);
    },
    placeholderData: (previous) => previous,
    enabled,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.datasets.all() }),
    [queryClient],
  );

  // No `onError`: a taken name is something the reader fixes in the dialog
  // still on screen, so the dialog owns where to say it.
  const create = useMutation({
    mutationFn: (dataset: NewDataset) => apiClient.post<Dataset>("/datasets", dataset),
    onSuccess: async (dataset) => {
      await invalidate();
      toast.success(t("created", { name: dataset.name }));
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/datasets/${id}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("deleted"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  return {
    datasets: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    isFetching,
    error,
    refetch,
    create,
    remove,
  };
}

/** One dataset, and renaming or redescribing it - which is not a new version. */
export function useDataset(datasetId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.datasets.detail(datasetId),
    queryFn: () => apiClient.get<Dataset>(`/datasets/${datasetId}`),
  });
  const update = useMutation({
    mutationFn: (changes: Partial<NewDataset>) =>
      apiClient.patch<Dataset>(`/datasets/${datasetId}`, changes),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.datasets.all() }),
  });
  return { dataset: query.data, isLoading: query.isLoading, error: query.error, update };
}

/** Every version of a dataset, newest first. */
export function useDatasetVersions(datasetId: string) {
  const { data, isLoading } = useQuery({
    queryKey: qk.datasets.versions(datasetId),
    queryFn: () => apiClient.get<DatasetVersionList>(`/datasets/${datasetId}/versions?limit=100`),
  });
  return { versions: data?.items ?? [], isLoading };
}

/**
 * A page of one version's cases, and the changes that each make a new version.
 *
 * `version` null reads the newest. Every mutation invalidates the whole dataset:
 * a change moves the newest version, its count and the version list at once.
 */
export function useDatasetCases(
  datasetId: string,
  {
    version = null,
    skip = 0,
    limit = PAGE_SIZE,
  }: { version?: number | null; skip?: number; limit?: number } = {},
) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.datasets.cases(datasetId, { version, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
      if (version !== null) params.set("version", String(version));
      return apiClient.get<DatasetCaseList>(`/datasets/${datasetId}/cases?${params}`);
    },
    placeholderData: (previous) => previous,
  });

  const changed = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.datasets.all() }),
    [queryClient],
  );

  const add = useMutation({
    mutationFn: (content: DatasetCaseContent) =>
      apiClient.post<DatasetCase>(`/datasets/${datasetId}/cases`, content),
    onSuccess: async () => {
      await changed();
      toast.success(t("caseAdded"));
    },
  });

  const update = useMutation({
    mutationFn: ({ caseId, content }: { caseId: string; content: DatasetCaseContent }) =>
      apiClient.patch<DatasetCase>(`/datasets/${datasetId}/cases/${caseId}`, content),
    onSuccess: async () => {
      await changed();
      toast.success(t("caseSaved"));
    },
  });

  const remove = useMutation({
    mutationFn: (caseId: string) =>
      apiClient.delete<void>(`/datasets/${datasetId}/cases/${caseId}`),
    onSuccess: async () => {
      await changed();
      toast.success(t("caseRemoved"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  const importFile = useMutation({
    mutationFn: (file: File) =>
      apiClient.upload<DatasetVersion>(`/datasets/${datasetId}/import`, file),
    onSuccess: async (created) => {
      await changed();
      toast.success(t("imported", { count: created.changed_cases, version: created.number }));
    },
  });

  return {
    cases: data?.items ?? [],
    total: data?.total ?? 0,
    version: data?.version ?? 0,
    isLoading,
    error,
    refetch,
    add,
    update,
    remove,
    importFile,
  };
}

/** Download one version of a dataset as a file that imports back unchanged. */
export async function exportDataset(
  datasetId: string,
  { format, version }: { format: DatasetFileFormat; version: number | null },
): Promise<void> {
  const params: Record<string, string> = { format };
  if (version !== null) params.version = String(version);
  const response = await apiClient.raw(`/datasets/${datasetId}/export`, { params });
  const name = response.headers.get("content-disposition")?.match(/filename="([^"]+)"/)?.[1];
  saveBlob(await response.blob(), name ?? `dataset.${format}`);
}

/** What "Add to dataset" sends: which answer, and whether it is the bad or the good one. */
export interface AddFromMessage {
  datasetId: string;
  messageId: string;
  answerAs: "counter_example" | "reference_answer";
}

/** Turn an agent's answer into a case - from a conversation or from Activity. */
export function useAddToDataset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, messageId, answerAs }: AddFromMessage) =>
      apiClient.post<DatasetCase>(`/datasets/${datasetId}/cases/from-message`, {
        message_id: messageId,
        answer_as: answerAs,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.datasets.all() }),
  });
}
