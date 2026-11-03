"use client";

import { useLocale, useTranslations } from "next-intl";

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

/**
 * The last word before an edit goes live: a new version reaches the line's agents
 * on their next run, so it says how many, as the server counts them, and names the
 * ones the reader may see, with the way to check the change on them instead.
 * Checking runs each agent's questions with the new text and applies it from the
 * result; saving now applies it unchecked.
 */
export function SaveConfirmDialog({
  version,
  reach,
  readers,
  canCheck,
  onCheck,
  onSave,
  onCancel,
}: {
  /** The version the save makes: `v13`, or `Returns v3` on a fork. */
  version: string;
  /** How many agents the save reaches, every environment and hidden ones included. */
  reach: number;
  /** Those of them the reader may see, by name. */
  readers: string[];
  /** Whether the reader may run a check, which reads the agents' runs. */
  canCheck: boolean;
  onCheck: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const t = useTranslations("skills.page.edit.confirm");
  const locale = useLocale();
  const list = new Intl.ListFormat(locale, { type: "conjunction" });
  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("title", { version })}</DialogTitle>
          <DialogDescription>
            {reach === 0
              ? t("nobody")
              : t("reaches", {
                  count: reach,
                  names: list.format(readers),
                  named: readers.length > 0 ? "yes" : "no",
                })}
          </DialogDescription>
        </DialogHeader>
        {reach > 0 && canCheck && <p className="text-muted-foreground text-sm">{t("checkHint")}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            {t("back")}
          </Button>
          {reach > 0 && canCheck && (
            <Button variant="outline" onClick={onCheck}>
              {t("check")}
            </Button>
          )}
          <Button onClick={onSave}>{t("save")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
