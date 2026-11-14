"use client";

import { useState } from "react";
import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { AddToDatasetDialog } from "./add-to-dataset-dialog";
import type { AskedBefore } from "./follows-on";
import { useCanAddToDataset } from "./use-dataset-target";

interface AddToDatasetButtonProps {
  messageId: string;
  ratedDown: boolean;
  asked?: AskedBefore;
  answer?: string;
}

/**
 * "Add to dataset" on an agent's turn in Activity, where answers are curated - a
 * good one as a reference as much as a bad one as a counter-example. In chat the
 * rating decides: a thumbs-up offers it as a reference, a thumbs-down as a
 * counter-example.
 *
 * Not rendered for somebody with no dataset to add to - by role, or by a grant.
 */
export function AddToDatasetButton({
  messageId,
  ratedDown,
  asked,
  answer,
}: AddToDatasetButtonProps) {
  const t = useTranslations("datasets");
  const canAdd = useCanAddToDataset();
  const [open, setOpen] = useState(false);
  if (!canAdd) return null;
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} className="gap-2">
        <FlaskConical className="h-4 w-4" aria-hidden />
        {t("addToDataset")}
      </Button>
      {open && (
        <AddToDatasetDialog
          open={open}
          onOpenChange={setOpen}
          messageId={messageId}
          answerAs={ratedDown ? "counter_example" : "reference_answer"}
          askAnswerAs
          ratedDown={ratedDown}
          asked={asked}
          answer={answer}
        />
      )}
    </>
  );
}
