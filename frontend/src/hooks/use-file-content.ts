"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { openFileInNewTab, type FileAccess, type FileText } from "@/lib/file-access";

/**
 * Reading one open file, whatever surface it was opened from.
 *
 * All three hooks take a `FileAccess` rather than a file: which route answers, and
 * how, is the caller's business - a chat is authorised through its conversation and
 * an operator through the workspace's own id, and the viewer above must not learn
 * which of the four origins it was handed.
 *
 * They take one rather than a nullable one, because a file is read when a viewer is
 * opened on it and a viewer that is closed is not rendered. The "nothing is open"
 * case belongs to whoever owns that state, not to a query that would have to carry a
 * disabled branch and an idle key for it.
 */

interface UseFileTextResult {
  file: FileText | null;
  isLoading: boolean;
  error: string | null;
}

/** One file's characters. */
export function useFileText(access: FileAccess): UseFileTextResult {
  const t = useTranslations("files");
  const {
    data: file = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: access.textKey,
    queryFn: () => access.readText(),
    retry: false,
  });

  return { file, isLoading, error: readFailure(error, t("couldNotBeRead")) };
}

interface UseFileBytesResult {
  /** A blob URL for the bytes, or null while it is being fetched or on a failure. */
  url: string | null;
  /**
   * What the server said this is.
   *
   * Read off the response rather than guessed from the name. The API decides what may
   * be displayed inline - raster images and PDFs, never SVG or HTML, because either
   * served inline from this origin is stored XSS written by the agent - and a second
   * list of suffixes in the client is a second answer to that question. When the two
   * disagreed, `<img>` got a blob typed `application/octet-stream` and showed a broken
   * image with nothing saying why.
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
export function useFileBytes(access: FileAccess): UseFileBytesResult {
  const t = useTranslations("files");
  const {
    data: blob = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: access.bytesKey,
    queryFn: () => access.readBytes(),
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
    error: readFailure(error, t("couldNotBeRead")),
  };
}

interface UseFileActionsResult {
  download: () => void;
  openInNewTab: () => void;
  /** Why the last one did not do what it offered to, if it did not. */
  error: string | null;
}

/**
 * The two things somebody does with a file besides looking at it, with somewhere for
 * a refusal to go.
 *
 * The refusal is not hypothetical: a binary in a container-backed workspace is read
 * through an archive that can only read text, so the API answers 400 - and a bare
 * `void access.download()` turned exactly that into a button that did nothing at
 * all, on the one path where it was certain to fail.
 *
 * One error for both, because they fail for the same reason - the bytes could not be
 * fetched - and a second slot would only ever hold the same sentence.
 */
export function useFileActions(access: FileAccess): UseFileActionsResult {
  const t = useTranslations("files");
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(
    (action: () => Promise<void>) => {
      setError(null);
      void action().catch((failure: unknown) =>
        setError(failure instanceof Error ? failure.message : t("couldNotBeFetched")),
      );
    },
    [t],
  );

  return {
    download: useCallback(() => run(() => access.download()), [run, access]),
    openInNewTab: useCallback(() => run(() => openFileInNewTab(access)), [run, access]),
    error,
  };
}

/** `fallback` rather than a message of its own: a module function cannot translate. */
function readFailure(error: unknown, fallback: string): string | null {
  if (error instanceof Error) return error.message;
  return error ? fallback : null;
}
