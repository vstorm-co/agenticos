"use client";

import { useState } from "react";
import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import { AddToDatasetDialog } from "./add-to-dataset-dialog";

interface AddToDatasetButtonProps {
  messageId: string;
  ratedDown: boolean;
  /** `icon` beside the copy and rating controls in chat; `label` in Activity. */
  variant?: "icon" | "label";
  className?: string;
}

/**
 * "Add to dataset" on an agent's answer - in a conversation, or on a turn in Activity.
 *
 * Not rendered for somebody whose role edits no dataset: the dialog would offer
 * them nothing to add to.
 */
export function AddToDatasetButton({
  messageId,
  ratedDown,
  variant = "label",
  className,
}: AddToDatasetButtonProps) {
  const t = useTranslations("datasets");
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  if (!can(Perm.datasetsEdit)) return null;
  return (
    <>
      <Button
        variant="ghost"
        size={variant === "icon" ? "icon" : "sm"}
        aria-label={t("addToDataset")}
        title={t("addToDataset")}
        onClick={() => setOpen(true)}
        className={cn(variant === "icon" ? "h-6 w-6" : "h-7 gap-1.5 px-2 text-xs", className)}
      >
        <FlaskConical className="h-3.5 w-3.5" aria-hidden />
        {variant === "label" && t("addToDataset")}
      </Button>
      {open && (
        <AddToDatasetDialog
          open={open}
          onOpenChange={setOpen}
          messageId={messageId}
          ratedDown={ratedDown}
        />
      )}
    </>
  );
}
