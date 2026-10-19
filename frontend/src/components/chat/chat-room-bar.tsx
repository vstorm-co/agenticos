"use client";

import { useState } from "react";
import { UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { ChatPerson } from "@/types";
import { PersonFace } from "./person-face";
import { ShareDialog } from "./share-dialog";

/** Faces shown before the rest of the room folds into a count. */
const FACES = 4;

interface ChatRoomBarProps {
  conversationId: string;
  /** Who has the conversation open, the reader included. */
  present: ChatPerson[];
  /** The reader's own id, so they are listed last and as "you". */
  meId: string | undefined;
  /** Whether the reader may share the conversation - its owner may. */
  canShare: boolean;
  className?: string;
}

/**
 * Who else is in this conversation right now, over the top of it.
 *
 * Drawn only when somebody else is: a chat the reader has to themselves needs no
 * bar saying so. The faces carry a live dot, the way a shared document shows
 * who has it open, and the owner can invite somebody else in from here.
 */
export function ChatRoomBar({
  conversationId,
  present,
  meId,
  canShare,
  className,
}: ChatRoomBarProps) {
  const t = useTranslations("chat.room");
  const [sharing, setSharing] = useState(false);
  const others = present.filter((person) => person.user_id !== meId);
  if (others.length === 0) return null;

  const shown = others.slice(0, FACES);
  const more = others.length - shown.length;
  const names = others.map((person) => person.name);

  return (
    <div
      className={cn(
        "bg-background/85 border-border/60 flex items-center gap-3 rounded-xl border px-3 py-1.5 backdrop-blur",
        className,
      )}
    >
      <span className="flex shrink-0 items-center" aria-hidden>
        {shown.map((person, index) => (
          <span key={person.user_id} className={cn("relative", index > 0 && "-ml-1.5")}>
            <PersonFace person={person} className="ring-background h-6 w-6 text-[9px] ring-2" />
            <span className="bg-success ring-background absolute -right-px -bottom-px h-2 w-2 rounded-full ring-2" />
          </span>
        ))}
        {more > 0 && (
          <span className="bg-muted text-muted-foreground ring-background -ml-1.5 grid h-6 min-w-6 place-items-center rounded-full px-1 text-[10px] font-medium ring-2">
            {t("more", { count: more })}
          </span>
        )}
      </span>
      <span
        className="text-muted-foreground min-w-0 flex-1 truncate text-xs"
        title={names.join(", ")}
      >
        {/* `name` is read only for one other person, when the list is their name. */}
        {t("here", { count: others.length, name: names.join(", ") })}
      </span>
      {canShare && (
        <>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 shrink-0 gap-1.5 px-2 text-xs"
            onClick={() => setSharing(true)}
          >
            <UserPlus className="h-3.5 w-3.5" aria-hidden />
            {t("share")}
          </Button>
          <ShareDialog conversationId={conversationId} open={sharing} onOpenChange={setSharing} />
        </>
      )}
    </div>
  );
}
