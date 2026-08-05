"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  bytesKey,
  readFileBytes,
  readFileText,
  textKey,
  type FileSource,
  type FileText,
} from "@/lib/workspace-files";

/**
 * Reading one open file.
 *
 * Both hooks take a file rather than a nullable one, because a file is read when a
 * viewer is opened on it - and a viewer that is closed is not rendered. The
 * "nothing is open" case belongs to whoever owns that state, not to a query that
 * would have to carry a disabled branch and an idle key for it.
 */

interface UseFileTextResult {
  file: FileText | null;
  isLoading: boolean;
  error: string | null;
}

/** One file's text. */
export function useWorkspaceFileText(source: FileSource, path: string): UseFileTextResult {
  const {
    data: file = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: textKey(source, path),
    queryFn: () => readFileText(source, path),
    retry: false,
  });

  return {
    file,
    isLoading,
    error: error instanceof Error ? error.message : error ? "That file could not be read" : null,
  };
}

interface UseFileBytesResult {
  /** A blob URL for the bytes, or null while it is being fetched or on a failure. */
  url: string | null;
  /**
   * What the server said this is.
   *
   * Read off the response rather than guessed from the suffix. The API decides what
   * may be displayed inline - raster images and PDFs, never SVG or HTML, because
   * either served inline from this origin is stored XSS written by the agent - and a
   * second list of suffixes in the client is a second answer to that question. When
   * the two disagreed, `<img>` got a blob typed `application/octet-stream` and showed
   * a broken image with nothing saying why.
   */
  mediaType: string | null;
  isLoading: boolean;
  error: string | null;
}

/**
 * One file's bytes as a URL something can render.
 *
 * A blob URL rather than pointing an `<img>` or an `<iframe>` at the API: a browser
 * request carries no organization header, and the backend would answer for the
 * caller's personal organization instead of the one on screen. Revoked on unmount,
 * because a blob URL holds the bytes alive until it is.
 */
export function useWorkspaceFileBytes(source: FileSource, path: string): UseFileBytesResult {
  const {
    data: blob = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: bytesKey(source, path),
    queryFn: () => readFileBytes(source, path),
    retry: false,
  });

  // A memo and a cleanup rather than state written from an effect: `createObjectURL`
  // is synchronous, so there is nothing to wait for, and a `setState` in an effect is
  // a second render for a value that was already available in the first.
  const url = useMemo(() => (blob === null ? null : URL.createObjectURL(blob)), [blob]);
  useEffect(
    () => () => {
      // A blob URL holds the bytes alive until it is revoked, and a PDF or a chart
      // adds up over a session of clicking through files.
      if (url !== null) URL.revokeObjectURL(url);
    },
    [url],
  );

  return {
    url,
    mediaType: blob?.type ?? null,
    isLoading,
    error: error instanceof Error ? error.message : error ? "That file could not be read" : null,
  };
}

interface UseFileDownloadResult {
  download: (path: string) => void;
  /** Why the last attempt did not produce a file, if it did not. */
  error: string | null;
}

/**
 * Downloading a file, with somewhere for the refusal to go.
 *
 * The refusal is not hypothetical: a binary in a container-backed workspace is read
 * through an archive that can only read text, so the API answers 400 - and a bare
 * `void downloadWorkspaceFile(...)` turned exactly that into a button that did
 * nothing at all, on the one path where it was certain to fail.
 */
export function useFileDownload(source: FileSource): UseFileDownloadResult {
  const [error, setError] = useState<string | null>(null);
  const download = useCallback(
    (path: string) => {
      setError(null);
      void downloadWorkspaceFile(source, path).catch((failure: unknown) =>
        setError(failure instanceof Error ? failure.message : "That file could not be downloaded"),
      );
    },
    [source],
  );

  return { download, error };
}

/** Save a workspace file to disk, keeping the name it has in the workspace. */
export async function downloadWorkspaceFile(source: FileSource, path: string): Promise<void> {
  const blob = await readFileBytes(source, path, { download: true });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = path.split("/").filter(Boolean).pop() ?? "file";
  link.click();
  // On the next tick, not immediately. A blob URL left alive keeps the whole file in
  // memory for the life of the page, so it has to be revoked - but Firefox and Safari
  // read the URL *after* the click handler returns, and revoking synchronously
  // cancels the download there. Chrome tolerates it, which is exactly how this ships
  // broken for half the users.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
