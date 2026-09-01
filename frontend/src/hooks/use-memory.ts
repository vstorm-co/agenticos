"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { PAGE_SIZE } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { MemoryFile, MemoryFileList } from "@/types/memory";

/** How the server may order a file listing. */
export type MemorySort = "name" | "updated";

/**
 * Which partition to list.
 *
 * `all` spans every partition; `shared` is the one store every end-user reads.
 * The per-user partitions are surfaced within `all` by their partition badge —
 * a dedicated per-user filter is a later step, because naming an end-user needs
 * an identity the raw `user:`/`chan:` key does not carry.
 */
export type MemoryScope = "all" | "shared";

/** The fields an operator sets when authoring a trusted memory file. */
interface NewMemoryFile {
  name: string;
  description: string | null;
  content: string;
  format: string;
  kind: string;
  /** The partition to write to; omit (null) for the shared store. */
  end_user_scope_key: string | null;
}

/** What the editor may change on a file that already exists — never its name. */
export interface MemoryEdit {
  description: string | null;
  content: string;
  format: string;
  kind: string;
}

interface MemoryFilesQuery {
  agentId: string;
  scope?: MemoryScope;
  search?: string;
  sort?: MemorySort;
  skip?: number;
  limit?: number;
}

/**
 * One agent's memory files, a page at a time.
 *
 * The list omits every body (an agent's whole memory is not something to ship to
 * draw a table), so searching, sorting and paging all happen on the server and
 * `total` is the count before paging. Creating a file here always writes an
 * operator-authored (trusted) row; the agent's own writes arrive through its
 * runtime tools with `origin="agent"`.
 */
export function useMemoryFiles({
  agentId,
  scope = "all",
  search = "",
  sort = "name",
  skip = 0,
  limit = PAGE_SIZE,
}: MemoryFilesQuery) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("memory");
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.memory.files(agentId, { scope, search, sort, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams({ agent_id: agentId, partition: scope, sort });
      if (search) params.set("q", search);
      params.set("skip", String(skip));
      params.set("limit", String(limit));
      return apiClient.get<MemoryFileList>(`/memory/files?${params}`);
    },
    placeholderData: (previous) => previous,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.memory.all(agentId) }),
    [queryClient, agentId],
  );

  // Like `useContextFiles.create`: no `onError`, because every way a create
  // fails — the name is taken in this partition, a field is too long — is fixed
  // in the dialog still on screen, which owns where to say it.
  const create = useMutation({
    mutationFn: (file: NewMemoryFile) =>
      apiClient.post<MemoryFile>("/memory/files", { agent_id: agentId, ...file }),
    onSuccess: async (file) => {
      await invalidate();
      toast.success(t("created", { name: file.name }));
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/memory/files/${id}`),
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
    remove,
  };
}

/**
 * One memory file, body included — what the editor opens.
 *
 * Separate from the list because the list omits `content`. Saving edits a file
 * in place; promoting marks an agent-authored file trusted, which is the only
 * way its body becomes injectable — editing one never launders its origin, so a
 * promote is a deliberate, separate act.
 */
export function useMemoryFile(agentId: string, fileId: string | null) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("memory");
  const queryClient = useQueryClient();

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.memory.all(agentId) }),
    [queryClient, agentId],
  );

  const { data, isLoading } = useQuery({
    queryKey: qk.memory.file(fileId ?? ""),
    queryFn: () => apiClient.get<MemoryFile>(`/memory/files/${fileId}`),
    enabled: fileId !== null,
  });

  const save = useMutation({
    mutationFn: (edit: MemoryEdit) => apiClient.patch<MemoryFile>(`/memory/files/${fileId}`, edit),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("saved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const promote = useMutation({
    mutationFn: () => apiClient.post<MemoryFile>(`/memory/files/${fileId}/promote`, {}),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("promoted"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return { file: data, isLoading, save, promote };
}
