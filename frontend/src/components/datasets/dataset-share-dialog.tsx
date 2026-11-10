"use client";

import { useTranslations } from "next-intl";

import { SharingPanel } from "@/components/sharing/sharing-panel";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { Dataset } from "@/types/datasets";

interface DatasetShareDialogProps {
  dataset: Dataset;
  onOpenChange: (open: boolean) => void;
}

/** Who sees the dataset and who may change it; read-only for someone who may not edit it. */
export function DatasetShareDialog({ dataset, onOpenChange }: DatasetShareDialogProps) {
  const t = useTranslations("datasets");
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{t("shareTitle", { name: dataset.name })}</DialogTitle>
          <DialogDescription>{t("shareBody")}</DialogDescription>
        </DialogHeader>
        <SharingPanel resourceType="dataset" resourceId={dataset.id} canManage={dataset.can_edit} />
      </DialogContent>
    </Dialog>
  );
}
