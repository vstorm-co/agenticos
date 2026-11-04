"use client";
import { useShellEvent } from "./use-desktop";

/** Only the originating socket stops a turn; another conversation or follower cannot. */
export function useDesktopRunControl(
  conversation: string | null,
  processing: boolean,
  following: () => boolean,
  stop: () => void,
) {
  useShellEvent("desktop:stop-conversation", (requested) => {
    if (
      typeof requested === "string" &&
      conversation !== null &&
      requested === conversation &&
      processing &&
      !following()
    )
      stop();
  });
}
