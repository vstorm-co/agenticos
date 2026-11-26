"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  applyBundleTransfer,
  cancelBundleTransfer,
  getBundleTransfer,
  startBundleExport,
  startBundleUpload,
  uploadBundleFile,
  type ImportChoice,
  type BundleRootKind,
  type TransferOperation,
} from "@/lib/portability-api";
import {
  readTransferSession,
  subscribeTransferSessions,
  transferSessionKey,
  writeTransferSession,
} from "@/lib/transfer-session";
import { invalidateImportedResources } from "@/lib/bundle-cache";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";

/** Restore only an owner-scoped operation ID; polling never starts another worker job. */
export function useBundleTransfer(enabled: boolean, scope?: string) {
  const t = useTranslations("portability");
  const [selected, setSelected] = useState<{ owner: string | null; id: string | null }>({
    owner: null,
    id: null,
  });
  const client = useQueryClient();
  const user = useAuthStore((state) => state.user?.id ?? null);
  const org = useOrgStore((state) => state.activeOrgId);
  const storageKey = transferSessionKey(org, user, scope);
  const owner = storageKey ?? JSON.stringify([org, user]);
  const savedId = useSyncExternalStore(
    subscribeTransferSessions,
    () => readTransferSession(storageKey),
    () => null,
  );
  const id = selected.owner === owner ? selected.id : savedId;
  const key = (identity: string | null) => qk.portability.transfer(org, user, identity);
  const remember = async (row: TransferOperation) => {
    await client.cancelQueries({ queryKey: key(row.id) });
    client.setQueryData(key(row.id), row);
    writeTransferSession(storageKey, row.id);
    setSelected({ owner, id: row.id });
  };
  const transfer = useQuery({
    queryKey: key(id),
    queryFn: async ({ signal }) => {
      if (!id) throw new Error(t("noTransferSelected"));
      return getBundleTransfer(id, signal);
    },
    enabled: enabled && id !== null,
    staleTime: 0,
    retry: false,
    refetchInterval: (query) =>
      query.state.status !== "error" &&
      ["queued", "running"].includes(query.state.data?.status ?? "")
        ? 1000
        : false,
  });
  const exportZip = useMutation({
    onMutate: (): void => discard.reset(),
    mutationFn: (data: {
      rootId: string;
      resources: Record<string, string[]>;
      requestId: string;
      rootKind?: BundleRootKind;
    }) => startBundleExport(data.rootId, data.resources, data.requestId, data.rootKind),
    onSuccess: remember,
  });
  const uploadZip = useMutation({
    onMutate: (): void => discard.reset(),
    mutationFn: async (data: { file: File; requestId: string }) => {
      const previous = id ? await getBundleTransfer(id) : null;
      const ticket = previous ?? (await startBundleUpload(data.file, data.requestId));
      await remember(ticket);
      if (ticket.status !== "awaiting_upload") return ticket;
      return uploadBundleFile(ticket.id, data.file);
    },
    onSuccess: remember,
  });
  const apply = useMutation({
    onMutate: (): void => discard.reset(),
    mutationFn: (choices: Record<string, ImportChoice>) => {
      if (!id || !transfer.data) throw new Error(t("noReviewedTransfer"));
      return applyBundleTransfer(id, transfer.data.revision, choices);
    },
    onSuccess: async (row) => {
      await remember(row);
    },
  });
  const discard = useMutation({
    mutationFn: async (target: {
      id: string | null;
      owner: string;
      storageKey: string | null;
      org: string | null;
      user: string | null;
    }) => {
      if (target.id) await cancelBundleTransfer(target.id);
    },
    onSuccess: async (_, target) => {
      await client.cancelQueries({
        queryKey: qk.portability.transfer(target.org, target.user, target.id),
      });
      if (readTransferSession(target.storageKey) === target.id)
        writeTransferSession(target.storageKey, null);
      if (
        useOrgStore.getState().activeOrgId !== target.org ||
        (useAuthStore.getState().user?.id ?? null) !== target.user ||
        owner !== target.owner
      )
        return;
      setSelected({ owner: target.owner, id: null });
      exportZip.reset();
      uploadZip.reset();
      apply.reset();
    },
  });
  const reset = async (): Promise<boolean> => {
    const target = { id, owner, storageKey, org, user };
    try {
      await discard.mutateAsync(target);
      return (
        useOrgStore.getState().activeOrgId === target.org &&
        (useAuthStore.getState().user?.id ?? null) === target.user
      );
    } catch {
      // The mutation exposes this refusal; retain the ticket until cancellation succeeds.
      return false;
    }
  };
  const accepted = transfer.isFetchedAfterMount && !transfer.isError;
  const invalidatedReceipt = useRef<string | null>(null);
  const receipt = accepted ? transfer.data?.receipt : null;
  useEffect(() => {
    if (receipt && id && invalidatedReceipt.current !== id) {
      invalidatedReceipt.current = id;
      void invalidateImportedResources(client, receipt);
    }
  }, [client, id, receipt]);
  return {
    restoreFailed: id !== null && transfer.isError,
    transfer: { ...transfer, data: accepted ? transfer.data : undefined },
    exportZip,
    uploadZip,
    apply,
    reset,
    busy:
      discard.isPending ||
      exportZip.isPending ||
      uploadZip.isPending ||
      apply.isPending ||
      transfer.isFetching ||
      (accepted && ["queued", "running"].includes(transfer.data?.status ?? "")),
    error: discard.error ?? transfer.error ?? exportZip.error ?? uploadZip.error ?? apply.error,
  };
}
