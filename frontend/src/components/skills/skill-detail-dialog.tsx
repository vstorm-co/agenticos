"use client";

import { useTranslations } from "next-intl";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui";
import { SkillDetails } from "./skill-details";

/** Read a skill without leaving the catalog; full workspaces remain directly linkable. */
export function SkillDetailDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const t = useTranslations("skills.page");
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-w-6xl pt-12 sm:pt-12" aria-describedby={undefined}>
        <DialogTitle className="sr-only">{t("skillDetails")}</DialogTitle>
        <SkillDetails key={id} id={id} inDialog onDeleted={onClose} />
      </DialogContent>
    </Dialog>
  );
}
