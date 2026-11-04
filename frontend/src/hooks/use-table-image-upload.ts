"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";
import { uploadTableImage } from "@/lib/tables-api";

export function useTableImageUpload(tableId?: string) {
  const t = useTranslations("tables.markdown");
  return useCallback(
    async (file: File): Promise<{ id: string; url: string }> => {
      if (!tableId) throw new Error(t("imageUploadError"));
      return uploadTableImage(tableId, file);
    },
    [tableId, t],
  );
}
