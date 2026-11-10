"use client";
import { useTranslations } from "next-intl";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { CreateOrgForm } from "./create-org-form";

interface CreateOrgDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (id: string) => void;
}
export function CreateOrgDialog({ open, onOpenChange, onCreated }: CreateOrgDialogProps) {
  const t = useTranslations("teams");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("createOrganization")}</DialogTitle>
        </DialogHeader>
        <CreateOrgForm
          onCreated={(id) => {
            onOpenChange(false);
            onCreated?.(id);
          }}
          onCancel={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}
