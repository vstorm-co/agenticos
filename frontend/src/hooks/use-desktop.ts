"use client";

import { useEffect, useEffectEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  getDesktopState,
  pinAgent,
  setBlobby,
  setShortcut,
  setWindowPreferences,
  unpinAgent,
  type BlobbySettings,
  type DesktopState,
  type PinnedAgent,
  type ShortcutAction,
  type WindowPreferences,
} from "@/lib/desktop/commands";
import { listenShell, reportShellFailure } from "@/lib/desktop/shell";
import { qk } from "@/lib/query-keys";
import { useShell } from "@/hooks/use-shell";

/** What the desktop app holds for this person; disabled, and `undefined`, in a browser. */
export function useDesktopState() {
  const shell = useShell();
  return useQuery({
    queryKey: qk.desktop.state(),
    queryFn: getDesktopState,
    enabled: shell !== null,
    // Not server data and not shared: nothing changes it but this person, and
    // every change below writes the answer back into the cache itself.
    staleTime: Infinity,
  });
}

/** A change to the desktop app's state, written to the cache as soon as the shell takes it. */
function useDesktopChange<T, A>(
  send: (value: T) => Promise<A>,
  apply: (state: DesktopState, value: T, answer: A) => DesktopState,
) {
  const queryClient = useQueryClient();
  const t = useTranslations("desktop");
  return useMutation({
    mutationFn: send,
    onSuccess: (answer, value) =>
      queryClient.setQueryData<DesktopState>(qk.desktop.state(), (state) =>
        state ? apply(state, value, answer) : state,
      ),
    // The shell's reasons are English and written for a log; the person reads the catalog's.
    onError: (error) => {
      reportShellFailure("a change was refused", error);
      toast.error(t("changeFailed"));
    },
  });
}

export function useSetBlobby() {
  return useDesktopChange(setBlobby, (state, blobby: BlobbySettings) => ({ ...state, blobby }));
}

/** Pin an agent to "New Chat With" in the tray and the Dock, or take it off. */
export function useSetPinned() {
  return useDesktopChange(
    ({ agent, pinned }: { agent: PinnedAgent; pinned: boolean }) =>
      pinned ? pinAgent(agent) : unpinAgent(agent.id),
    (state, _change, pinned) => ({ ...state, pinned }),
  );
}

export function useSetWindowPreferences() {
  return useDesktopChange(setWindowPreferences, (state, window: WindowPreferences) => ({
    ...state,
    window,
  }));
}

export function useSetShortcut() {
  return useDesktopChange(
    ({ action, accelerator }: { action: ShortcutAction; accelerator: string | null }) =>
      setShortcut(action, accelerator),
    (state, { action, accelerator }) => ({
      ...state,
      shortcuts: state.shortcuts.map((binding) =>
        binding.action === action ? { ...binding, accelerator, problem: null } : binding,
      ),
    }),
  );
}

/**
 * Listen for an event the desktop app sends this window, for as long as the
 * component is mounted. Nothing in a browser.
 *
 * The handler is an effect event, so a caller passing a fresh closure every
 * render does not re-subscribe - which, with a listener registered over IPC,
 * would leave a window between the old one going and the new one arriving.
 */
export function useShellEvent(event: string, handler: (payload: unknown) => void): void {
  const shell = useShell();
  const onEvent = useEffectEvent(handler);

  useEffect(() => {
    if (!shell) return;
    let unlisten: (() => void) | null = null;
    let gone = false;
    listenShell(event, (payload) => onEvent(payload))
      .then((stop) => {
        if (gone) stop();
        else unlisten = stop;
      })
      .catch((error: unknown) => reportShellFailure(event, error));
    return () => {
      gone = true;
      unlisten?.();
    };
  }, [event, shell]);
}
