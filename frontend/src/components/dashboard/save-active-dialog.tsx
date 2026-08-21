"use client";

import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";

interface SaveActiveDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whether a save is currently in flight, to disable the actions. */
  busy: boolean;
  /** Save only as the active arrangement — one slot, replaced on the next change. */
  onSaveActive: () => void;
  /** Keep it as a named, permanent template instead. */
  onSaveAsTemplate: () => void;
}

/**
 * The safeguard shown when a person saves a layout they built from a blank
 * start. A plain save writes the single *active* arrangement, which reset and
 * every applied layout overwrite — so a from-scratch layout saved that way is
 * one reset from being lost, with no name to bring it back. This names that
 * cost before it is paid and offers the permanent template instead; applying
 * for now stays one click away for the person who genuinely wants the throwaway.
 */
export function SaveActiveDialog({
  open,
  onOpenChange,
  busy,
  onSaveActive,
  onSaveAsTemplate,
}: SaveActiveDialogProps) {
  const t = useTranslations("dashboard");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("edit.tempSaveTitle")}</DialogTitle>
          <DialogDescription>{t("edit.tempSaveDescription")}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>
            {t("edit.cancel")}
          </Button>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button variant="outline" disabled={busy} onClick={onSaveActive}>
              {t("edit.tempSaveKeep")}
            </Button>
            <Button disabled={busy} onClick={onSaveAsTemplate}>
              {t("edit.tempSaveAsTemplate")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
