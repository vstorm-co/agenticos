"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useShellEvent } from "@/hooks/use-desktop";
import {
  cancelMuseAccount,
  manageCliAccount,
  type CliAccountAction,
  parseMuseAccountProgress,
  type MuseAccountProgress,
} from "@/lib/desktop/commands";
import { qk } from "@/lib/query-keys";

/** Device-code artifacts stay in this component's memory and the native account owner. */
export function useCliAccount(id: string) {
  const client = useQueryClient();
  const current = useRef<string | null>(null);
  const [progress, setProgress] = useState<MuseAccountProgress | null>(null);
  useShellEvent("external-account-progress", (payload) => {
    let next: MuseAccountProgress;
    try {
      next = parseMuseAccountProgress(payload);
    } catch {
      return;
    }
    if (next.requestId === current.current) setProgress(next);
  });
  const action = useMutation({
    mutationFn: ({ operation, requestId }: { operation: CliAccountAction; requestId: string }) =>
      manageCliAccount(id, requestId, operation),
    onSettled: (_result, _error, variables) => {
      if (current.current === variables.requestId) {
        current.current = null;
        setProgress(null);
      }
      void client.invalidateQueries({ queryKey: qk.desktop.externalAgents() });
      void client.invalidateQueries({ queryKey: qk.desktop.externalOptionsAll() });
    },
  });
  useEffect(
    () => () => {
      // Unmount is best effort; the native owner also expires the flow after ten minutes.
      if (current.current) void cancelMuseAccount(current.current).catch(() => {});
    },
    [],
  );
  const cancel = useMutation({
    mutationFn: async () => {
      if (current.current) await cancelMuseAccount(current.current);
    },
  });
  const start = (operation: CliAccountAction) => {
    if (current.current) return;
    const requestId = crypto.randomUUID();
    current.current = requestId;
    setProgress(null);
    action.mutate({ operation, requestId });
  };
  return { action, progress, cancel, start };
}
