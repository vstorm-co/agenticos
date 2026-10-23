"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { ChatPerson } from "@/types";
import { PersonFace } from "./person-face";

/**
 * Who else is writing a message in this chat, as a messenger says it: their
 * faces, three dots and a line of words. Empty when nobody is - the line
 * appears with the first keystroke heard and goes with the last.
 *
 * The region itself is always there: a screen reader announces a change inside
 * a live region it already knows, and says nothing of one that mounts with its
 * text already in it.
 */
export function TypingIndicator({
  people,
  className,
}: {
  people: ChatPerson[];
  className?: string;
}) {
  const t = useTranslations("chat.room");
  const names = people.map((person) => person.name);

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "text-muted-foreground flex items-center gap-2 px-1 text-xs",
        people.length > 0 && "pb-1.5",
        className,
      )}
    >
      {people.length > 0 && (
        <>
          <span className="flex shrink-0 items-center" aria-hidden>
            {people.slice(0, 3).map((person, index) => (
              <PersonFace
                key={person.user_id}
                person={person}
                className={cn("ring-background h-5 w-5 text-[8px] ring-2", index > 0 && "-ml-1.5")}
              />
            ))}
          </span>
          <span className="min-w-0 truncate">
            {t("typing", { count: people.length, name: names.join(", ") })}
          </span>
          <span className="typing-dots shrink-0" aria-hidden>
            <i />
            <i />
            <i />
          </span>
        </>
      )}
    </div>
  );
}
