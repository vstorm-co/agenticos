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
  /** Only the datasets the caller may change, by role or by a grant. */
  editable?: boolean;
  /** Only the datasets this judge grades. */
  judge?: string;
  /** Only the datasets whose newest version has a case asking this run's question. */
  asksRun?: string;
  /** False holds the request until it is needed, as a picker behind a checkbox is. */
  enabled?: boolean;
}

export interface NewDataset {
  name: string;
  description: string | null;
  /** Who sees it; the server makes it the organization's when this is left out. */
  visibility?: "org" | "private";
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
  editable = false,
  judge = "",
  asksRun = "",
  enabled = true,
}: DatasetQuery = {}) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: qk.datasets.list({ search, sort, skip, limit, editable, judge, asksRun }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      if (editable) params.set("editable", "true");
      if (judge) params.set("judge", judge);
      if (asksRun) params.set("asks_run", asksRun);
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

/**
 * One dataset: renaming or redescribing it - which is not a new version - and
 * deleting it. Idle without an id, for a page still reading which dataset it is.
 */
export function useDataset(datasetId: string) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.datasets.detail(datasetId),
    queryFn: () => apiClient.get<Dataset>(`/datasets/${datasetId}`),
    enabled: datasetId !== "",
  });
  const update = useMutation({
    mutationFn: (changes: Partial<NewDataset>) =>
      apiClient.patch<Dataset>(`/datasets/${datasetId}`, changes),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.datasets.all() }),
  });
  // The page leaves on success; its own query is dropped rather than refetched
  // into a 404 on the way out.
  const remove = useMutation({
    mutationFn: () => apiClient.delete<void>(`/datasets/${datasetId}`),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: qk.datasets.detail(datasetId) });
      await queryClient.invalidateQueries({ queryKey: qk.datasets.lists() });
      toast.success(t("deleted"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });
  return { dataset: query.data, isLoading: query.isLoading, error: query.error, update, remove };
}

/** One case as the newest version holds it, for a link that opens it; idle without an id. */
export function useDatasetCase(datasetId: string, caseId: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.datasets.case(datasetId, caseId ?? ""),
    queryFn: () => apiClient.get<DatasetCase>(`/datasets/${datasetId}/cases/${caseId}`),
    enabled: caseId !== null,
  });
  return { kase: data, isLoading: caseId !== null && isLoading, error };
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
/** The longest question checked for a twin; a URL holding a longer one may be refused. */
const TWIN_CHECK_MAX = 2_000;

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
    // A picker asks before a dataset is chosen; there is nothing to read until one is.
    enabled: datasetId !== "",
    placeholderData: (previous) => previous,
  });

  const changed = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.datasets.all() }),
    [queryClient],
  );
  // The version a change made, once the dataset has been read again; 0 where it
  // was not, and the toast then names no number.
  const made = useCallback(async () => {
    await changed();
    return queryClient.getQueryData<Dataset>(qk.datasets.detail(datasetId))?.latest_version ?? 0;
  }, [changed, queryClient, datasetId]);

  const add = useMutation({
    mutationFn: (content: DatasetCaseContent) =>
      apiClient.post<DatasetCase>(`/datasets/${datasetId}/cases`, content),
    onSuccess: async () => toast.success(t("caseAdded", { version: await made() })),
  });

  const update = useMutation({
    mutationFn: ({ caseId, content }: { caseId: string; content: DatasetCaseContent }) =>
      apiClient.patch<DatasetCase>(`/datasets/${datasetId}/cases/${caseId}`, content),
    onSuccess: async () => toast.success(t("caseSaved", { version: await made() })),
  });

  const remove = useMutation({
    mutationFn: (caseId: string) =>
      apiClient.delete<void>(`/datasets/${datasetId}/cases/${caseId}`),
    onSuccess: async () => toast.success(t("caseRemoved", { version: await made() })),
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

  // Read when a new case is saved, never cached: the answer must be as of now. A
  // question too long to travel in a URL is not checked, rather than refused.
  const findTwin = useCallback(
    async (input: string): Promise<DatasetCase | null> => {
      if (input.length > TWIN_CHECK_MAX) return null;
      const params = new URLSearchParams({ same_input: input, limit: "1" });
      const found = await apiClient.get<DatasetCaseList>(`/datasets/${datasetId}/cases?${params}`);
      return found.items[0] ?? null;
    },
    [datasetId],
  );

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
    findTwin,
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
