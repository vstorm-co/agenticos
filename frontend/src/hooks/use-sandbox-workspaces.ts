"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  listAllWorkspaceFiles,
  listWorkspaces,
  readWorkspaceFiles,
  type FlatFileList,
  type WorkspaceFiles,
  type WorkspaceSummary,
} from "@/lib/sandbox-workspaces-api";

interface UseWorkspacesResult {
  /** Hosts that would not answer. A shorter answer, said rather than implied. */
  unreadable: number;
  truncated: boolean;
  workspaces: WorkspaceSummary[];
  isLoading: boolean;
  error: string | null;
}

/**
 * Every workspace this organization's agents keep.
 *
 * Rows only, and no polling: a workspace's *contents* change when an agent runs,
 * but the list of them changes when a conversation starts or is deleted - which
 * is not something worth a request every ten seconds.
 */
export function useSandboxWorkspaces(measure = false): UseWorkspacesResult {
  const t = useTranslations("pages.workspaces");
  const tErrors = useTranslations("errors");
  // Keyed on the flag, so turning counting on is a new query rather than a refetch
  // that replaces the cheap answer with the expensive one and back again.
  const { data, isLoading, error } = useQuery({
    queryKey: qk.sandboxWorkspaces.list(measure),
    queryFn: () => listWorkspaces(measure),
  });

  return {
    workspaces: data?.items ?? [],
    unreadable: data?.unreadable ?? 0,
    truncated: data?.truncated ?? false,
    isLoading,
    error: error ? getErrorMessage(error, tErrors, t("failedLoadWorkspaces")) : null,
  };
}

interface UseAllWorkspaceFilesResult {
  listing: FlatFileList | null;
  isLoading: boolean;
  error: string | null;
}

/**
 * Every file the caller can see, in one list.
 *
 * Only fetched when the flat view is on. It reads each workspace in turn - a round
 * trip per container-backed one - so it is not what a page pays for on load.
 */
export function useAllWorkspaceFiles(enabled: boolean): UseAllWorkspaceFilesResult {
  const t = useTranslations("pages.workspaces");
  const tErrors = useTranslations("errors");
  const {
    data: listing = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: qk.sandboxWorkspaces.allFiles(),
    queryFn: listAllWorkspaceFiles,
    enabled,
    retry: false,
  });

  return {
    listing,
    isLoading: enabled && isLoading,
    error: error ? getErrorMessage(error, tErrors, t("failedLoadWorkspaces")) : null,
  };
}

interface UseWorkspaceFilesResult {
  files: WorkspaceFiles | null;
  isLoading: boolean;
  error: string | null;
}

/**
 * What one workspace holds.
 *
 * Read only when a workspace is opened, which is the whole reason the listing
 * carries no files: this is a query per row and nobody wants all of them.
 */
export function useWorkspaceFiles(workspaceId: string | null): UseWorkspaceFilesResult {
  const t = useTranslations("pages.workspaces");
  const tErrors = useTranslations("errors");
  const {
    data: files = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: qk.sandboxWorkspaces.files(workspaceId ?? "none"),
    queryFn: () => readWorkspaceFiles(workspaceId as string),
    enabled: workspaceId !== null,
    retry: false,
  });

  return {
    files,
    isLoading: workspaceId !== null && isLoading,
    error: error ? getErrorMessage(error, tErrors, t("workspaceUnreadable")) : null,
  };
}

// Reading one file - its text, its bytes, or onto the caller's disk - lives in
// `use-workspace-file.ts`, which takes the workspace *or* the conversation it is
// addressed through. It used to live here and take a workspace id, which is why the
// chat panel could only ever show text.
