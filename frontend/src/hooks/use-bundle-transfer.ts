"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  applyBundleTransfer,
  getBundleTransfer,
  startBundleExport,
  startBundleUpload,
  uploadBundleFile,
  type ImportChoice,
  type TransferOperation,
} from "@/lib/portability-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";

/** Transfer IDs stay on the server; polling never starts another worker job. */
export function useBundleTransfer(enabled: boolean) {
  const t = useTranslations("portability");
  const [id, setId] = useState<string | null>(null);
  const client = useQueryClient();
  const user = useAuthStore((state) => state.user?.id ?? null);
  const org = useOrgStore((state) => state.activeOrgId);
  const key = (identity: string | null) => qk.portability.transfer(org, user, identity);
  const remember = async (row: TransferOperation) => {
    await client.cancelQueries({ queryKey: key(row.id) });
    client.setQueryData(key(row.id), row);
    setId(row.id);
  };
  const transfer = useQuery({
    queryKey: key(id),
    queryFn: ({ signal }) => {
      if (!id) throw new Error(t("noTransferSelected"));
      return getBundleTransfer(id, signal);
    },
    enabled: enabled && id !== null,
    staleTime: Infinity,
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.status ?? "") ? 1000 : false,
  });
  const exportZip = useMutation({
    mutationFn: (data: {
      rootId: string;
      resources: Record<string, string[]>;
      requestId: string;
    }) => startBundleExport(data.rootId, data.resources, data.requestId),
    onSuccess: remember,
  });
  const uploadZip = useMutation({
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
    mutationFn: (choices: Record<string, ImportChoice>) => {
      if (!id || !transfer.data) throw new Error(t("noReviewedTransfer"));
      return applyBundleTransfer(id, transfer.data.revision, choices);
    },
    onSuccess: async (row) => {
      await remember(row);
      void client.invalidateQueries({ queryKey: qk.agents.all() });
    },
  });
  const reset = () => {
    setId(null);
    exportZip.reset();
    uploadZip.reset();
    apply.reset();
  };
  return {
    transfer,
    exportZip,
    uploadZip,
    apply,
    reset,
    busy:
      exportZip.isPending ||
      uploadZip.isPending ||
      apply.isPending ||
      ["queued", "running"].includes(transfer.data?.status ?? ""),
    error: transfer.error ?? exportZip.error ?? uploadZip.error ?? apply.error,
  };
}
