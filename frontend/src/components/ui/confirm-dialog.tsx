"use client";

import * as React from "react";

import { Button } from "./button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./dialog";
import { Input } from "./input";
import { Label } from "./label";
import { useChanged } from "@/hooks/use-changed";
import { useTranslations } from "next-intl";

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Style the confirm button as destructive (red). */
  destructive?: boolean;
  /**
   * When set, the user must type this exact string (e.g. the org name or
   * "DELETE") to enable the confirm button - for high-stakes actions.
   */
  confirmText?: string;
  /** Show a busy state on the confirm button while the action runs. */
  loading?: boolean;
  onConfirm: () => void | Promise<void>;
}

/**
 * Reusable confirmation dialog for destructive / irreversible actions.
 * Optionally requires typing a phrase to confirm. Replaces ad-hoc one-click
 * deletes across KB / orgs / collections / account.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel,
  destructive,
  confirmText,
  loading,
  onConfirm,
}: ConfirmDialogProps) {
  const t = useTranslations("ui");
  // Resolved in the body, not as a default parameter: the translator is declared here,
  // and a default cannot reach a value that does not exist yet.
  const confirmWords = confirmLabel ?? t("confirm");
  const cancelWords = cancelLabel ?? t("cancel");
  const [typed, setTyped] = React.useState("");

  // Cleared as the dialog closes, during render rather than in an effect: an
  // effect commits the typed value once more before clearing it.
  if (useChanged(open) && !open) setTyped("");

  const canConfirm = !loading && (!confirmText || typed.trim() === confirmText);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        {confirmText && (
          <div className="space-y-1.5">
            <Label htmlFor="confirm-phrase" className="text-muted-foreground text-xs">
              {t.rich("typeToConfirm", {
                phrase: confirmText,
                mono: (chunks) => <span className="text-foreground font-mono">{chunks}</span>,
              })}
            </Label>
            <Input
              id="confirm-phrase"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
              autoFocus
            />
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            {cancelWords}
          </Button>
          <Button
            variant={destructive ? "destructive" : "default"}
            disabled={!canConfirm}
            onClick={() => void onConfirm()}
          >
            {loading ? "…" : confirmWords}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
