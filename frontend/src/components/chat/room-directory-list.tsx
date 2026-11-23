"use client";

import { Loader2, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import type { Conversation } from "@/types/conversation";

interface RoomDirectoryListProps {
  rooms: Conversation[];
  isLoading: boolean;
  error: unknown;
  isJoining: boolean;
  joiningId: string | null;
  onRetry: () => void;
  onJoin: (id: string) => void;
}

/** Public room listing states and per-room join actions. */
export function RoomDirectoryList({
  rooms,
  isLoading,
  error,
  isJoining,
  joiningId,
  onRetry,
  onJoin,
}: RoomDirectoryListProps) {
  const t = useTranslations("chat.rooms");
  if (error) {
    return (
      <div role="alert" className="space-y-3">
        <p className="text-muted-foreground text-sm">{t("loadFailed")}</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t("retry")}
        </Button>
      </div>
    );
  }
  if (isLoading) {
    return (
      <p role="status" className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        {t("loading")}
      </p>
    );
  }
  if (rooms.length === 0) {
    return (
      <p className="text-muted-foreground rounded-lg border p-5 text-center text-sm">
        {t("empty")}
      </p>
    );
  }
  return (
    <ul className="divide-border divide-y">
      {rooms.map((room) => (
        <li key={room.id} className="flex min-w-0 items-center gap-3 py-3">
          <div className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-lg">
            <Users className="size-4" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{room.title}</p>
            <p className="text-muted-foreground text-xs">{t("public")}</p>
          </div>
          <Button size="sm" variant="outline" disabled={isJoining} onClick={() => onJoin(room.id)}>
            {joiningId === room.id && (
              <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
            )}
            {t("join")}
          </Button>
        </li>
      ))}
    </ul>
  );
}
