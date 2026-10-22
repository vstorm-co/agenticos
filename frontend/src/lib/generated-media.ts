"use client";

import { createContext, useContext } from "react";

/**
 * Where a generated image, clip of speech or video is being shown, which decides
 * the address its card fetches the file from (#2309).
 *
 * In the console the reader is signed in, and `/api/generated/{filename}` forwards
 * their session. A visitor on a hosted page has no session: their socket hands
 * them a `token` beside each file the conversation produced, and the file is read
 * through the page's own key with it. `session` is the default, so every surface
 * that is not a hosted page keeps the address it always had.
 */
export type MediaSurface = { kind: "session" } | { kind: "hosted"; publicKey: string };

export const SESSION_SURFACE: MediaSurface = { kind: "session" };

/** The surface the nearest provider declared, or the console's session. */
export const MediaSurfaceContext = createContext<MediaSurface>(SESSION_SURFACE);

export function useMediaSurface(): MediaSurface {
  return useContext(MediaSurfaceContext);
}

/**
 * The address a card fetches a generated file from, or null when it has none.
 *
 * Null for a file that was generated but not stored, and on a hosted page for a
 * result that carries no link - one the socket did not sign, which this visitor
 * could not open anyway.
 *
 * @param payload - The tool result, parsed: its `filename` and, on a hosted page,
 *   the `token` the socket added.
 * @param surface - Where the card is shown.
 */
export function generatedMediaUrl(
  payload: { filename?: unknown; token?: unknown },
  surface: MediaSurface,
): string | null {
  const filename = typeof payload.filename === "string" ? payload.filename : null;
  if (filename === null) return null;
  if (surface.kind === "session") return `/api/generated/${filename}`;
  const token = typeof payload.token === "string" ? payload.token : null;
  if (token === null) return null;
  const key = encodeURIComponent(surface.publicKey);
  const name = encodeURIComponent(filename);
  return `/api/embed/${key}/generated/${name}?token=${encodeURIComponent(token)}`;
}
