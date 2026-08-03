"use client";

import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import {
  listAllWorkspaceFiles,
  listWorkspaces,
  readWorkspaceBytes,
  readWorkspaceFile,
  readWorkspaceFiles,
  type FlatFileList,
  type WorkspaceFileContent,
  type WorkspaceFiles,
  type WorkspaceSummary,
} from "@/lib/sandbox-workspaces-api";

interface UseWorkspacesResult {
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
export function useSandboxWorkspaces(): UseWorkspacesResult {
  const {
    data: workspaces = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: qk.sandboxWorkspaces.list(),
    queryFn: listWorkspaces,
  });

  return {
    workspaces,
    isLoading,
    error: error instanceof Error ? error.message : error ? "Failed to load workspaces" : null,
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
    error: error === null ? null : error.message,
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
    error:
      error instanceof Error ? error.message : error ? "That workspace could not be read" : null,
  };
}

interface UseWorkspaceFileResult {
  file: WorkspaceFileContent | null;
  isLoading: boolean;
  error: string | null;
}

/** One file's text, fetched when somebody opens it and not before. */
export function useWorkspaceFile(
  workspaceId: string | null,
  path: string | null,
): UseWorkspaceFileResult {
  const {
    data: file = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: qk.sandboxWorkspaces.file(workspaceId ?? "none", path ?? "none"),
    queryFn: () => readWorkspaceFile(workspaceId as string, path as string),
    enabled: workspaceId !== null && path !== null,
    retry: false,
  });

  return {
    file,
    isLoading: workspaceId !== null && path !== null && isLoading,
    error: error instanceof Error ? error.message : error ? "That file could not be read" : null,
  };
}

interface UseWorkspaceBytesResult {
  /** A blob URL for the bytes, or null while it is being fetched or on a failure. */
  url: string | null;
  isLoading: boolean;
  error: string | null;
}

/**
 * One file's bytes as a URL something can render.
 *
 * A blob URL rather than pointing an `<img>` at the API: a browser request carries
 * no organization header, and the backend would answer for the caller's personal
 * organization instead of the one on screen. Revoked on unmount, because a blob URL
 * holds the bytes alive until it is.
 */
export function useWorkspaceBytes(
  workspaceId: string | null,
  path: string | null,
): UseWorkspaceBytesResult {
  const {
    data: blob = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: qk.sandboxWorkspaces.bytes(workspaceId ?? "none", path ?? "none"),
    queryFn: () => readWorkspaceBytes(workspaceId as string, path as string),
    enabled: workspaceId !== null && path !== null,
    retry: false,
  });

  // A memo and a cleanup rather than state written from an effect: `createObjectURL`
  // is synchronous, so there is nothing to wait for, and a `setState` in an effect is
  // a second render for a value that was already available in the first.
  const url = useMemo(() => (blob === null ? null : URL.createObjectURL(blob)), [blob]);
  useEffect(
    () => () => {
      // A blob URL holds the bytes alive until it is revoked, and an image the size
      // of a chart adds up over a session of clicking through files.
      if (url !== null) URL.revokeObjectURL(url);
    },
    [url],
  );

  return {
    url,
    isLoading: workspaceId !== null && path !== null && isLoading,
    error: error === null ? null : error.message,
  };
}

/** Save a workspace file to disk, keeping the name it has in the workspace. */
export async function downloadWorkspaceFile(workspaceId: string, path: string): Promise<void> {
  const blob = await readWorkspaceBytes(workspaceId, path, { download: true });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = path.split("/").filter(Boolean).pop() ?? "file";
  link.click();
  // Immediately: the click has already handed the bytes to the download, and a URL
  // left alive keeps the whole file in memory for the life of the page.
  URL.revokeObjectURL(url);
}
