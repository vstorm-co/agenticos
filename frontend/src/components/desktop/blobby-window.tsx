"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Blobby, type Heard } from "@/components/desktop/blobby";
import { useAuth } from "@/hooks/use-auth";
import { useBlobbyActivity } from "@/hooks/use-blobby-activity";
import { useDesktopState, useShellEvent } from "@/hooks/use-desktop";
import { useLiveUpdates } from "@/hooks/use-live-updates";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { parseBlobbySettings, type DesktopState } from "@/lib/desktop/commands";
import { reportShellFailure, SHELL_EVENTS } from "@/lib/desktop/shell";
import { qk } from "@/lib/query-keys";

/**
 * The page in blobby's window: who it is (the shell's settings, kept current by
 * the shell's event), whether anybody is signed in, and what their agents are
 * doing - read with this page's own session, the console's cookie.
 *
 * Nobody signed in is not an error here: blobby dozes, and a click says where
 * to sign in. A redirect to the sign-in page inside a 200px transparent window
 * would be a form nobody can use.
 */
export function BlobbyWindow() {
  const queryClient = useQueryClient();
  const { data } = useDesktopState();
  const { isAuthenticated, isLoading } = useAuth();
  const signedIn = isAuthenticated && !isLoading;
  const activity = useBlobbyActivity(signedIn);
  const reducedMotion = useReducedMotion();
  const [heard, setHeard] = useState<Heard | null>(null);
  const t = useTranslations("desktop.blobby");
  useLiveUpdates();

  useShellEvent(SHELL_EVENTS.blobby, (payload) => {
    try {
      const blobby = parseBlobbySettings(payload);
      queryClient.setQueryData<DesktopState>(qk.desktop.state(), (state) =>
        state ? { ...state, blobby } : state,
      );
    } catch (error) {
      reportShellFailure("blobby's new settings could not be read", error);
    }
  });
  // A file dragged over blobby: it says it will take it, and the shell opens a
  // chat with whatever is dropped.
  useShellEvent(SHELL_EVENTS.blobbyDrop, (payload) => {
    if (payload === "enter") setHeard((last) => ({ text: t("dropHere"), id: (last?.id ?? 0) + 1 }));
  });
  useShellEvent(SHELL_EVENTS.say, (payload) => {
    if (typeof payload === "string")
      setHeard((last) => ({ text: payload, id: (last?.id ?? 0) + 1 }));
  });

  if (!data) return null;
  return (
    <Blobby
      settings={data.blobby}
      activity={activity}
      signedIn={signedIn}
      heard={heard}
      reducedMotion={reducedMotion}
    />
  );
}
