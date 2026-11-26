"use client";

import { useTranslations } from "next-intl";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui";

/**
 * The explicit way past a test: saving without one is allowed, but only after
 * being told what it risks. The server records that the save was unverified.
 */
export function UnverifiedSaveDialog({
  open,
  onOpenChange,
  onConfirm,
  affected,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  /** How many knowledge bases the change reaches. */
  affected: number;
}) {
  const t = useTranslations("kb");
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("unverifiedTitle")}</AlertDialogTitle>
          <AlertDialogDescription>{t("unverifiedBody")}</AlertDialogDescription>
        </AlertDialogHeader>
        {affected > 0 && (
          <p className="text-muted-foreground text-sm">
            {t("unverifiedAffected", { count: affected })}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            onClick={onConfirm}
          >
            {t("unverifiedConfirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
