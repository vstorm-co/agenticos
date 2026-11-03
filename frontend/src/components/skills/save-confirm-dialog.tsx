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
 * on their next run, so they are named first, with the way to check the change on
 * them instead. Checking runs each agent's questions with the new text and applies
 * it from the result; saving now applies it unchecked.
 */
export function SaveConfirmDialog({
  version,
  readers,
  hidden,
  canCheck,
  saving,
  onCheck,
  onSave,
  onCancel,
}: {
  /** The version the save makes: `v13`, or `Returns v3` on a fork. */
  version: string;
  /** The agents following the line that the reader may see. */
  readers: string[];
  /** Agents following the line that the reader may not see. */
  hidden: number;
  /** Whether the reader may run a check, which reads the agents' runs. */
  canCheck: boolean;
  saving: boolean;
  onCheck: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const t = useTranslations("skills.page.edit.confirm");
  const locale = useLocale();
  const count = readers.length + hidden;
  const list = new Intl.ListFormat(locale, { type: "conjunction" });
  return (
    <Dialog open onOpenChange={(open) => !open && !saving && onCancel()}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("title", { version })}</DialogTitle>
          <DialogDescription>
            {count === 0
              ? t("nobody")
              : t("reaches", {
                  count,
                  names: list.format(readers),
                  named: readers.length > 0 ? "yes" : "no",
                  hidden,
                })}
          </DialogDescription>
        </DialogHeader>
        {count > 0 && canCheck && <p className="text-muted-foreground text-sm">{t("checkHint")}</p>}
        <DialogFooter>
          <Button variant="outline" disabled={saving} onClick={onCancel}>
            {t("back")}
          </Button>
          {count > 0 && canCheck && (
            <Button variant="outline" disabled={saving} onClick={onCheck}>
              {t("check")}
            </Button>
          )}
          <Button loading={saving} onClick={onSave}>
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
