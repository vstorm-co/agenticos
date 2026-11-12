"use client";

import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Skeleton,
} from "@/components/ui";
import { EditorLoading } from "@/components/files/editor-loading";
import { DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";

/** The catalog's chunk and data loading states use the editor's actual canvas size. */
export function SkillEditorLoadingDialog({
  name,
  canEdit,
  onClose,
}: {
  name?: string;
  canEdit?: boolean;
  onClose?: () => void;
}) {
  const t = useTranslations("skills");
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose?.();
      }}
    >
      <DialogContent className={cn(DIALOG_FILL, DIALOG_CANVAS, "max-md:overflow-y-auto")}>
        <DialogHeader>
          <div className="flex min-w-0 items-center justify-between gap-3 pr-8">
            <DialogTitle className="min-w-0 font-mono [overflow-wrap:anywhere]">
              {name ?? t("page.skillDetails")}
            </DialogTitle>
            <Skeleton className="touch:min-h-11 h-8 w-8 shrink-0 rounded-md sm:w-32" aria-hidden />
          </div>
          <DialogDescription>{t("page.edit.nameHowModelRefers")}</DialogDescription>
        </DialogHeader>
        <EditorLoading kind="skill" canEdit={canEdit} />
      </DialogContent>
    </Dialog>
  );
}
