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
} from "@/components/ui/alert-dialog";
import type { RoomParticipantRead } from "@/types/room";

export interface RoomParticipantAction {
  kind: "add" | "remove";
  participant: RoomParticipantRead;
}

interface RoomParticipantConfirmationProps {
  action: RoomParticipantAction | null;
  isLegacyDirect: boolean;
  isPending: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

/** Make history access and membership removal explicit before the API write. */
export function RoomParticipantConfirmation({
  action,
  isLegacyDirect,
  isPending,
  error,
  onOpenChange,
  onConfirm,
}: RoomParticipantConfirmationProps) {
  const t = useTranslations("chat.roomParticipants");
  const tc = useTranslations("common");
  if (action === null) return null;

  const adding = action.kind === "add";
  const directAdd = adding && isLegacyDirect;
  const title = adding
    ? directAdd
      ? t("historyDirectTitle")
      : t("historyRoomTitle", { name: action.participant.name })
    : t("removeTitle", { name: action.participant.name });
  const description = adding
    ? directAdd
      ? t("historyDirectDescription", { name: action.participant.name })
      : t("historyRoomDescription")
    : t("removeDescription");

  return (
    <AlertDialog
      open
      onOpenChange={(open) => {
        if (!open && !isPending) onOpenChange(false);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isPending}>{tc("cancel")}</AlertDialogCancel>
          <AlertDialogAction
            disabled={isPending}
            className={
              adding
                ? undefined
                : "bg-destructive text-destructive-foreground hover:bg-destructive/90"
            }
            onClick={(event) => {
              event.preventDefault();
              onConfirm();
            }}
          >
            {adding ? t(directAdd ? "confirmConvert" : "confirmAdd") : t("remove")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
