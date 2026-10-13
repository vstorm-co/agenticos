"use client";

import { useState } from "react";
import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { AddToDatasetDialog } from "./add-to-dataset-dialog";

interface AddToDatasetButtonProps {
  messageId: string;
  ratedDown: boolean;
}

/**
 * "Add to dataset" on an agent's turn in Activity, where answers are curated - a
 * good one as a reference as much as a bad one as a counter-example. In chat the
 * same choice is offered only in the rate-down dialog.
 *
 * Not rendered for somebody whose role edits no dataset: the dialog would offer
 * them nothing to add to.
 */
export function AddToDatasetButton({ messageId, ratedDown }: AddToDatasetButtonProps) {
  const t = useTranslations("datasets");
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  if (!can(Perm.datasetsEdit)) return null;
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(true)}
        className="h-7 gap-1.5 px-2 text-xs"
      >
        <FlaskConical className="h-3.5 w-3.5" aria-hidden />
        {t("addToDataset")}
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
