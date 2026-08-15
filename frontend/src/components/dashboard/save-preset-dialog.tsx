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
  /**
   * Save the current arrangement under `name`. Rejects on a duplicate name or
   * the per-person cap (the dialog reports that and stays open). Resolves to
   * `false` when a *later* step of a composite save failed and already reported
   * itself — the blank-start "save as template" also applies the layout — so
   * the dialog neither claims success nor closes on a half-done action.
   */
  onSave: (name: string) => Promise<boolean>;
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

  // Each open is a fresh name: reset on the way out, so cancelling and
  // reopening does not show the stale name from last time.
  const handleOpenChange = (next: boolean) => {
    if (!next) setName("");
    onOpenChange(next);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      if (await onSave(trimmed)) {
        toast.success(t("presets.saved", { name: trimmed }));
        handleOpenChange(false);
      }
      // A `false` means a later step failed and reported itself; leave the
      // dialog open without a contradicting success toast.
    } catch {
      toast.error(t("presets.saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
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
              onClick={() => handleOpenChange(false)}
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
