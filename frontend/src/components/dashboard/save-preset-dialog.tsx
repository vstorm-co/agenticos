"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";

interface SavePresetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Create the preset. Rejects on a duplicate name or the per-person cap. */
  onSave: (name: string) => Promise<void>;
}

/**
 * Name-and-save for the current arrangement. The name is required and the
 * save can be refused server-side - a name already used, or the preset cap -
 * so a rejection keeps the dialog open with a toast rather than closing on a
 * save that did not happen.
 */
export function SavePresetDialog({ open, onOpenChange, onSave }: SavePresetDialogProps) {
  const t = useTranslations("dashboard");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      await onSave(trimmed);
      toast.success(t("presets.saved", { name: trimmed }));
      setName("");
      onOpenChange(false);
    } catch {
      toast.error(t("presets.saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{t("presets.saveTitle")}</DialogTitle>
            <DialogDescription>{t("presets.saveDescription")}</DialogDescription>
          </DialogHeader>
          <div className="my-4 space-y-2">
            <Label htmlFor="preset-name">{t("presets.nameLabel")}</Label>
            <Input
              id="preset-name"
              value={name}
              maxLength={60}
              autoFocus
              placeholder={t("presets.namePlaceholder")}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => onOpenChange(false)}
            >
              {t("edit.cancel")}
            </Button>
            <Button type="submit" disabled={busy || name.trim().length === 0}>
              {t("edit.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
