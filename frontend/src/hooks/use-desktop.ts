"use client";

import { useCallback, useEffect, useEffectEvent, useMemo } from "react";
import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  changeServer,
  getLocalServices,
  saveLocalService,
  removeLocalService,
  type LocalService,
  DEVICE_STATUS_EVENT,
  getDesktopState,
  getDeviceStatus,
  getLocalState,
  linkDevice,
  listLocalFiles,
  pickLocalFolder,
  revokeLocalFolder,
  type LocalMode,
  parseDeviceStatus,
  unlinkDevice,
  type DeviceStatus,
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
import { getErrorMessage } from "@/lib/api-error";
import type { ConversationFile, ConversationWorkspace } from "@/lib/conversation-workspace-api";
import { isDesktopShell, listenShell, reportShellFailure } from "@/lib/desktop/shell";
import { createPairingCode } from "@/lib/pairing-api";
import { qk } from "@/lib/query-keys";
import { useShell } from "@/hooks/use-shell";

/** Open the trusted server picker without depending on blobby or the tray. */
export function useChangeServer() {
  const t = useTranslations("desktop.server");
  return useMutation({
    mutationFn: changeServer,
    onError: (error) => {
      reportShellFailure("opening the server picker", error);
      toast.error(t("changeFailed"));
    },
  });
}

/** What the desktop app holds for this person; disabled, and `undefined`, in a browser. */
export function useDesktopState() {
  const shell = useShell();
  return useQuery({
    queryKey: qk.desktop.state(),
    queryFn: getDesktopState,
    enabled: isDesktopShell(shell),
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
export function useShellEvent(
  event: string,
  handler: (payload: unknown) => void,
  enabled = true,
): void {
  const shell = useShell();
  const onEvent = useEffectEvent(handler);

  useEffect(() => {
    if (!shell || !enabled) return;
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
  }, [event, shell, enabled]);
}

/**
 * Whether this computer is linked and connected (#2305), kept current by the
 * shell's own events; disabled in a browser.
 */
export function useDeviceStatus() {
  const shell = useShell();
  const queryClient = useQueryClient();
  useShellEvent(
    DEVICE_STATUS_EVENT,
    (payload) => queryClient.setQueryData(qk.desktop.device(), parseDeviceStatus(payload)),
    isDesktopShell(shell),
  );
  return useQuery({
    queryKey: qk.desktop.device(),
    queryFn: getDeviceStatus,
    enabled: isDesktopShell(shell),
    staleTime: Infinity,
  });
}

/** Link or unlink this computer; linking mints a pairing code the shell redeems. */
export function useDeviceLink() {
  const queryClient = useQueryClient();
  const t = useTranslations("desktop.settings.device");
  const settle = (status: DeviceStatus) => queryClient.setQueryData(qk.desktop.device(), status);
  const link = useMutation({
    mutationFn: async () => linkDevice((await createPairingCode()).code),
    onSuccess: settle,
    onError: (error) => {
      reportShellFailure("linking this computer", error);
      toast.error(t("linkFailed"));
    },
  });
  const unlink = useMutation({
    mutationFn: unlinkDevice,
    onSuccess: settle,
    onError: (error) => {
      reportShellFailure("unlinking this computer", error);
      toast.error(t("unlinkFailed"));
    },
  });
  return { link, unlink };
}

/** The folders agents may work in on this computer, and picking or revoking one (#2305). */
export function useLocalFolders() {
  const shell = useShell();
  const queryClient = useQueryClient();
  const t = useTranslations("chat.controls.workOn");
  const state = useQuery({
    queryKey: qk.desktop.local(),
    queryFn: getLocalState,
    enabled: isDesktopShell(shell),
  });
  const pick = useMutation({
    mutationFn: (mode: LocalMode) => pickLocalFolder(mode),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.desktop.local() }),
    onError: (error) => {
      reportShellFailure("picking a folder", error);
      toast.error(t("pickFailed"));
    },
  });
  const revoke = useMutation({
    mutationFn: revokeLocalFolder,
    onSuccess: (next) => queryClient.setQueryData(qk.desktop.local(), next),
    onError: (error) => reportShellFailure("revoking a folder", error),
  });
  return { state, pick, revoke };
}

/**
 * The files in a folder on this computer, for a chat working there (#2305), in
 * the shape the chat's file panel reads. The app lists only a folder the person
 * granted; `null` turns it off.
 */
export function useLocalWorkspace(root: string | null, ownerLabel: string) {
  const shell = useShell();
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const enabled = isDesktopShell(shell) && root !== null;
  const { data, error } = useQuery({
    queryKey: qk.desktop.localFiles(root ?? "none"),
    queryFn: root === null ? skipToken : () => listLocalFiles(root),
    enabled,
    retry: false,
  });
  const refresh = useCallback(async () => {
    if (root === null) return;
    await queryClient.invalidateQueries({ queryKey: qk.desktop.localFiles(root) });
  }, [queryClient, root]);
  const workspace = useMemo<ConversationWorkspace | null>(() => {
    if (!enabled || data === undefined) return null;
    const items = data.map((file): ConversationFile => ({
      path: file.path,
      size: file.size,
      is_dir: file.is_dir,
      modified_at: file.modified === null ? null : new Date(file.modified * 1000).toISOString(),
      preview: null,
      thumbnail: null,
    }));
    return {
      scope: "local",
      backend: "local",
      owner_label: ownerLabel,
      items,
      total: items.length,
      bytes_total: items.reduce((sum, file) => sum + (file.size ?? 0), 0),
      bytes_limit: null,
      unreadable_reason: null,
    };
  }, [enabled, data, ownerLabel]);
  return { workspace, error: error ? getErrorMessage(error, tErrors) : null, refresh };
}

/** Native grants for loopback models and MCP; changes are confirmed by the app. */
export function useLocalServices() {
  const shell = useShell();
  const client = useQueryClient();
  const state = useQuery({
    queryKey: qk.desktop.services(),
    queryFn: getLocalServices,
    enabled: isDesktopShell(shell),
  });
  const settle = (services: LocalService[]) => client.setQueryData(qk.desktop.services(), services);
  const failed = (error: Error) => reportShellFailure("changing local services", error);
  const save = useMutation({ mutationFn: saveLocalService, onSuccess: settle, onError: failed });
  const remove = useMutation({
    mutationFn: removeLocalService,
    onSuccess: settle,
    onError: failed,
  });
  return { state, save, remove };
}
