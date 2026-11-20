"use client";

import { useTranslations } from "next-intl";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@/components/ui";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { appConnectionLabel } from "@/lib/app-connection-journey";
import type { AppConnection } from "@/types/app-connections";

export function ConnectionDisconnectDialog({
  connection,
  busy,
  error,
  onClose,
  onConfirm,
}: {
  connection: AppConnection;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const t = useTranslations("appConnections");
  return (
    <AlertDialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <AlertDialogContent className={DIALOG_CONFIRM}>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("disconnectTitle")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("disconnectHint", { account: appConnectionLabel(connection) })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && (
          <p className="text-destructive text-sm" role="alert">
            {error}
          </p>
        )}
        <AlertDialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button variant="destructive" loading={busy} onClick={onConfirm}>
            {t("disconnect")}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
