"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { PAGE_SIZE } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { MemoryFact, MemoryFactList, MemoryFile, MemoryFileList } from "@/types/memory";

/** How the server may order a file listing. */
export type MemorySort = "name" | "updated";

/**
 * Which partition to list.
 *
 * `all` spans every partition, `shared` the one store every end-user reads, and
 * `per_user` every private per-end-user store at once. A `per_user` listing
 * shows the raw `user:`/`chan:` key rather than a person's name — naming the
 * end-user behind a key needs an identity the key does not carry, a later step.
 */
export type MemoryScope = "all" | "shared" | "per_user";

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

  const { data, isLoading, error } = useQuery({
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
    () => queryClient.invalidateQueries({ queryKey: qk.memory.filesRoot(agentId) }),
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

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.memory.file(agentId, fileId ?? ""),
    queryFn: () => apiClient.get<MemoryFile>(`/memory/files/${fileId}`),
    enabled: fileId !== null,
  });

  // Write the result over the open file's cache, then refresh the lists. A bare
  // list invalidation would leave the editor showing the pre-write body — the
  // detail query does not refetch on its own, and after a promote that is the
  // difference between the file reading trusted and reading untrusted.
  const settle = useCallback(
    (updated: MemoryFile) => {
      queryClient.setQueryData(qk.memory.file(agentId, fileId ?? ""), updated);
      return queryClient.invalidateQueries({ queryKey: qk.memory.filesRoot(agentId) });
    },
    [queryClient, agentId, fileId],
  );

  const save = useMutation({
    mutationFn: (edit: MemoryEdit) => apiClient.patch<MemoryFile>(`/memory/files/${fileId}`, edit),
    onSuccess: async (updated) => {
      await settle(updated);
      toast.success(t("saved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const promote = useMutation({
    mutationFn: () => apiClient.post<MemoryFile>(`/memory/files/${fileId}/promote`, {}),
    onSuccess: async (updated) => {
      await settle(updated);
      toast.success(t("promoted"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return { file: data, isLoading, error, refetch, save, promote };
}

interface MemoryFactsQuery {
  agentId: string;
  scope?: MemoryScope;
  search?: string;
  skip?: number;
  limit?: number;
}

/** The fields an operator sets when seeding a fact directly. */
interface NewMemoryFact {
  content: string;
  /** The partition to write to; omit (null) for the shared store. */
  end_user_scope_key: string | null;
}

/**
 * One agent's remembered facts, a page at a time.
 *
 * Newest first (the server's order — a fact has no name to sort by), and the
 * search is a substring match on the content, never a semantic one: a KNN query
 * would embed the operator's text off the run's spend ledger. Facts are the
 * agent's to write; an operator only reviews and forgets them.
 */
export function useMemoryFacts({
  agentId,
  scope = "all",
  search = "",
  skip = 0,
  limit = PAGE_SIZE,
}: MemoryFactsQuery) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("memory");
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.memory.facts(agentId, { scope, search, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams({ agent_id: agentId, partition: scope });
      if (search) params.set("q", search);
      params.set("skip", String(skip));
      params.set("limit", String(limit));
      return apiClient.get<MemoryFactList>(`/memory/facts?${params}`);
    },
    placeholderData: (previous) => previous,
  });

  const create = useMutation({
    mutationFn: (fact: NewMemoryFact) =>
      apiClient.post<MemoryFact>("/memory/facts", { agent_id: agentId, ...fact }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.memory.factsRoot(agentId) });
      toast.success(t("factCreated"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  // Promoting an agent-authored fact makes it operator-trusted, which is what lets
  // it enter the standing brief — the fact counterpart of a file's promote. There
  // is no open detail to reconcile as there is for a file, so a plain list
  // invalidation is enough: the row re-renders operator, and its promote control
  // disappears with the origin it was gated on.
  const promote = useMutation({
    mutationFn: (id: string) => apiClient.post<MemoryFact>(`/memory/facts/${id}/promote`, {}),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.memory.factsRoot(agentId) });
      toast.success(t("promoted"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/memory/facts/${id}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.memory.factsRoot(agentId) });
      toast.success(t("factForgotten"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    facts: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    refetch,
    create,
    promote,
    remove,
  };
}

/**
 * The two danger-zone clears.
 *
 * `clearMemory` deletes every file and fact for the agent in every partition
 * (so it invalidates the whole agent root); `clearFacts` deletes only the facts.
 * Both are single agent-scoped requests, so a confirm dialog is the only guard
 * the UI owes them.
 */
export function useMemoryDangerZone(agentId: string) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("memory");
  const queryClient = useQueryClient();

  const clearMemory = useMutation({
    mutationFn: () => apiClient.delete<void>(`/memory?agent_id=${agentId}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.memory.all(agentId) });
      toast.success(t("cleared"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const clearFacts = useMutation({
    mutationFn: () => apiClient.delete<void>(`/memory/facts?agent_id=${agentId}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.memory.factsRoot(agentId) });
      toast.success(t("factsCleared"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return { clearMemory, clearFacts };
}
