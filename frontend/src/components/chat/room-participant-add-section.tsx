"use client";

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import type { RoomParticipantRead } from "@/types/room";
import { RoomParticipantPicker } from "./room-participant-picker";

interface RoomParticipantAddSectionProps {
  candidates: RoomParticipantRead[];
  isLoading: boolean;
  error: unknown;
  disabled: boolean;
  onRetry: () => void;
  onAdd: (participant: RoomParticipantRead) => void;
}

/** Show eligible join candidates, including a visible error state on load failure. */
export function RoomParticipantAddSection({
  candidates,
  isLoading,
  error,
  disabled,
  onRetry,
  onAdd,
}: RoomParticipantAddSectionProps) {
  const t = useTranslations("chat.roomParticipants");

  return (
    <section aria-labelledby="room-participant-add-heading" className="space-y-2">
      <h3 id="room-participant-add-heading" className="text-sm font-medium">
        {t("add")}
      </h3>
      {isLoading ? (
        <p role="status" className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
          {t("loading")}
        </p>
      ) : error ? (
        <div role="alert" className="space-y-2">
          <p className="text-muted-foreground text-sm">{t("mentionablesFailed")}</p>
          <Button variant="outline" size="sm" onClick={onRetry}>
            {t("retry")}
          </Button>
        </div>
      ) : (
        <RoomParticipantPicker candidates={candidates} disabled={disabled} onAdd={onAdd} />
      )}
    </section>
  );
}
