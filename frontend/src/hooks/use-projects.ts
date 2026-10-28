"use client";

import { useCallback, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { PAGE_SIZE } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import {
  createProject,
  createProjectFolder,
  deleteProject,
  getProject,
  listProjectChats,
  listProjectFiles,
  listProjects,
  moveProjectPath,
  moveProjectWorkspace,
  projectOfConversation,
  removeProjectPath,
  updateProject,
  uploadProjectFile,
} from "@/lib/projects-api";
import type { UploadProgress } from "@/hooks/use-knowledge-bases";
import { useTenantId } from "@/hooks/use-organizations";
import { qk } from "@/lib/query-keys";
import type { ProjectCreate, ProjectUpdate } from "@/types/projects";

export interface ProjectsQuery {
  search?: string;
  skip?: number;
  limit?: number;
  enabled?: boolean;
}

/**
 * The projects the caller may see, most recently changed first.
 *
 * Searched and paged on the server, so `total` is the count before paging. No
 * `onError` on create: a name too long is something the reader fixes in the
 * dialog still on screen, so the dialog owns where to say it.
 */
export function useProjects({
  search = "",
  skip = 0,
  limit = PAGE_SIZE,
  enabled = true,
}: ProjectsQuery = {}) {
  const t = useTranslations("projects");
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.projects.list({ search, skip, limit }),
    queryFn: () => listProjects({ search, skip, limit }),
    enabled,
    placeholderData: (previous) => previous,
  });

  const create = useMutation({
    mutationFn: (input: ProjectCreate) => createProject(input),
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: qk.projects.all() });
      toast.success(t("created", { name: project.name }));
    },
  });

  return {
    projects: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    refetch,
    create,
  };
}

/** One project, and what its editor may change about it. */
export function useProject(projectId: string) {
  const t = useTranslations("projects");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: qk.projects.detail(projectId),
    queryFn: () => getProject(projectId),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.workspace_move?.status ?? "") ? 1500 : false,
    retry: false,
  });

  const update = useMutation({
    mutationFn: (changes: ProjectUpdate) => updateProject(projectId, changes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.projects.all() });
      toast.success(t("saved"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  const remove = useMutation({
    mutationFn: () => deleteProject(projectId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.projects.all() });
      // Its chats stay, as ordinary ones, so the chat list has changed too.
      await queryClient.invalidateQueries({ queryKey: qk.conversations.all() });
      toast.success(t("deleted"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  const moveWorkspace = useMutation({
    mutationFn: (target: string) => moveProjectWorkspace(projectId, target),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.projects.all() });
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });
  return { project: data ?? null, isLoading, error, update, remove, moveWorkspace };
}

/** A path inside the project for a file being uploaded: a folder upload keeps its tree. */
export function uploadPath(file: File, folder: string): string {
  const relative = file.webkitRelativePath || file.name;
  return folder ? `${folder}/${relative}` : relative;
}

/**
 * The files a project holds, and adding or removing them.
 *
 * Uploads go one request per file: a folder of a hundred files is a hundred
 * writes into the container either way, and one refusal - a file over the limit -
 * then names that file rather than failing the batch.
 */
export function useProjectFiles(projectId: string) {
  const t = useTranslations("projects");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: qk.projects.files(projectId),
    queryFn: () => listProjectFiles(projectId),
    retry: false,
  });

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.projects.detail(projectId) }),
    [projectId, queryClient],
  );

  // One bar per file still in the air, as a knowledge base's upload shows them:
  // all of a folder's files are listed at once and go one by one.
  const organizationId = useTenantId();
  const [uploads, setUploads] = useState<UploadProgress[]>([]);
  const nextUpload = useRef(0);
  const failed = t("uploadFailed");

  const upload = useMutation({
    mutationFn: async ({ files, folder }: { files: File[]; folder: string }) => {
      const queued = files.map((file) => ({
        file,
        uploadId: `${nextUpload.current++}`,
      }));
      setUploads((current) => [
        ...current,
        ...queued.map(({ file, uploadId }) => ({ uploadId, filename: file.name, percent: 0 })),
      ]);
      try {
        for (const { file, uploadId } of queued) {
          await uploadProjectFile(projectId, file, uploadPath(file, folder), {
            organizationId,
            failed,
            onPercent: (percent) =>
              setUploads((current) =>
                current.map((entry) =>
                  entry.uploadId === uploadId ? { ...entry, percent } : entry,
                ),
              ),
          });
          setUploads((current) => current.filter((entry) => entry.uploadId !== uploadId));
        }
      } finally {
        // A refusal stops the batch; what had not gone yet is no longer coming.
        const ids = new Set(queued.map(({ uploadId }) => uploadId));
        setUploads((current) => current.filter((entry) => !ids.has(entry.uploadId)));
      }
      return files.length;
    },
    onSuccess: (count) => toast.success(t("uploaded", { count })),
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
    onSettled: refresh,
  });

  const addFolder = useMutation({
    mutationFn: (path: string) => createProjectFolder(projectId, path),
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
    onSettled: refresh,
  });

  const move = useMutation({
    mutationFn: ({ source, destination }: { source: string; destination: string }) =>
      moveProjectPath(projectId, source, destination),
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
    onSettled: refresh,
  });

  const remove = useMutation({
    mutationFn: (path: string) => removeProjectPath(projectId, path),
    onSuccess: () => toast.success(t("removed")),
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
    onSettled: refresh,
  });

  return {
    files: data ?? null,
    isLoading,
    error: error ? getErrorMessage(error, tErrors, t("filesUnreadable")) : null,
    upload,
    uploads,
    addFolder,
    move,
    remove,
  };
}

/**
 * The reader's own chats in a project, most recent first.
 *
 * Keyed under the conversation lists, so a chat started, renamed or archived
 * anywhere refreshes this too.
 */
/** Chats fetched per page of the project's list. */
export const PROJECT_CHATS_PAGE = 50;
const PROJECT_CHATS_POLL_MS = 20_000;

/** The project a conversation is in, or null; nothing is asked for a new chat. */
export function useProjectOfConversation(conversationId: string | null) {
  return useQuery({
    queryKey: qk.conversations.projectOf(conversationId ?? ""),
    queryFn: () => projectOfConversation(conversationId as string),
    enabled: conversationId !== null,
  });
}

/**
 * The project's chats, a page at a time, most recently active first.
 *
 * Paged rather than capped: a busy project outgrows any one page, and the
 * chats past it would otherwise drop out of the one list where teammates
 * find each other's.
 */
export function useProjectChats(projectId: string) {
  const { data, isLoading, error, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: qk.conversations.inProject(projectId),
      queryFn: ({ pageParam }) => listProjectChats(projectId, pageParam, PROJECT_CHATS_PAGE),
      // Who is in each chat, and whose run is at work, change while the page is
      // open; asked again on the same cadence a room's heartbeat keeps.
      refetchInterval: PROJECT_CHATS_POLL_MS,
      initialPageParam: 0,
      getNextPageParam: (last, pages) => {
        const loaded = pages.reduce((sum, page) => sum + page.items.length, 0);
        return loaded < last.total ? loaded : undefined;
      },
    });
  return {
    chats: data?.pages.flatMap((page) => page.items) ?? [],
    total: data?.pages[0]?.total ?? 0,
    isLoading,
    error,
    hasMore: hasNextPage,
    loadingMore: isFetchingNextPage,
    loadMore: () => void fetchNextPage(),
  };
}
