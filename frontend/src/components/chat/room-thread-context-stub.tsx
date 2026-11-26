"use client";

import { useTranslations } from "next-intl";
import type { RoomThreadMovedStub } from "@/types/room-thread-context";
import { Button } from "@/components/ui";

interface RoomThreadContextStubProps {
  stub: RoomThreadMovedStub;
  onOpen: (rootMessageId: string) => void;
}

/** A stable placeholder where a moved message range used to appear in the room. */
export function RoomThreadContextStub({ stub, onOpen }: RoomThreadContextStubProps) {
  const t = useTranslations("chat.roomThreadContext.stub");
  const title = stub.title.trim() || t("untitled");
  return (
    <div className="flex justify-center py-2" data-context-stub-root={stub.root_message_id}>
      <Button
        type="button"
        variant="outline"
        className="h-auto max-w-full justify-start gap-2 rounded-full px-3 py-2 text-left"
        aria-label={t("open", { title })}
        onClick={() => onOpen(stub.root_message_id)}
      >
        <span aria-hidden className="text-primary text-xs">
          ↗
        </span>
        <span className="min-w-0">
          <span className="block truncate text-xs font-medium">{title}</span>
          <span className="text-muted-foreground block text-[11px]">
            {t("detail", { count: stub.message_count })}
          </span>
        </span>
      </Button>
    </div>
  );
}
