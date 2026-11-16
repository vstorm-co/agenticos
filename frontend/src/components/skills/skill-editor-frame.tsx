"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";

/** Both the frame and footer protect the instruction draft and every open resource draft. */
export function leaveSkillEditor(id: string, proceed: () => void): void {
  const store = useUnsavedChangesStore.getState();
  const sources = [
    ...Object.keys(store.sources).filter((key) => key.startsWith(`skill-resource:${id}:`)),
    `skill-editor:${id}`,
  ];
  store.leave(proceed, sources);
}

/** Mount once: metadata and code loading replace the body, never the overlay or focus scope. */
export function SkillEditorFrame({
  id,
  title,
  description,
  busy = false,
  onClose,
  children,
}: {
  id: string;
  title?: string;
  description?: string;
  busy?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const t = useTranslations("skills");
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) leaveSkillEditor(id, onClose);
      }}
    >
      <DialogContent
        dismissible={!busy}
        className={cn(DIALOG_FILL, DIALOG_CANVAS, "max-md:overflow-y-auto")}
      >
        <DialogHeader>
          <DialogTitle className="min-w-0 font-mono [overflow-wrap:anywhere]">
            {title ?? t("page.skillDetails")}
          </DialogTitle>
          <DialogDescription>{description ?? t("page.edit.nameHowModelRefers")}</DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}
