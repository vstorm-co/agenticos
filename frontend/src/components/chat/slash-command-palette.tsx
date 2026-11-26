"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";

import { COMMAND_ITEM_FOCUS, MENU_ROW, MENU_LABEL } from "@/components/ui/control-styles";
import { cn } from "@/lib/utils";
import type { SlashCommand } from "./slash-commands";

interface SlashCommandPaletteProps {
  commands: SlashCommand[];
  selectedIndex: number;
  onSelectIndex: (i: number) => void;
  onPick: (cmd: SlashCommand) => void;
}

/** Floating palette rendered above the chat input when the user types `/`. */
export function SlashCommandPalette({
  commands,
  selectedIndex,
  onSelectIndex,
  onPick,
}: SlashCommandPaletteProps) {
  const t = useTranslations("chat.palette");
  const listRef = useRef<HTMLUListElement>(null);

  // Keep the highlighted row in view as the user arrow-keys through the list.
  useEffect(() => {
    const el = listRef.current?.children[selectedIndex] as HTMLElement | undefined;
    const list = listRef.current;
    if (!list || !el) return;
    const bounds = list.getBoundingClientRect();
    const row = el.getBoundingClientRect();
    if (row.top < bounds.top) list.scrollTop += row.top - bounds.top;
    else if (row.bottom > bounds.bottom) list.scrollTop += row.bottom - bounds.bottom;
  }, [selectedIndex]);

  if (commands.length === 0) {
    return (
      <div className="chat-command-palette border-border bg-popover absolute bottom-full left-0 mb-2 w-full max-w-[25rem] rounded-2xl border p-3 shadow-lg">
        <p className="text-muted-foreground text-xs">
          {t.rich("noMatching", {
            key: (chunks) => <kbd className="font-mono">{chunks}</kbd>,
          })}
        </p>
      </div>
    );
  }

  return (
    <div className="chat-command-palette border-border bg-popover absolute bottom-full left-0 mb-2 w-full max-w-[25rem] overflow-hidden rounded-2xl border shadow-lg">
      <div
        className={cn(MENU_LABEL, "chat-command-palette-header flex items-center justify-between")}
      >
        <span>{t("commands")}</span>
        <span className="hidden sm:inline">{t("hint")}</span>
      </div>
      <ul
        ref={listRef}
        className="max-h-[min(16rem,calc(var(--app-height,100dvh)*0.4))] scrollbar-thin overflow-y-auto overscroll-contain p-1.5"
      >
        {commands.map((cmd, i) => (
          <li
            key={cmd.name}
            onMouseEnter={() => onSelectIndex(i)}
            onMouseDown={(e) => {
              e.preventDefault(); // keep textarea focus
              onPick(cmd);
            }}
            className={cn(
              MENU_ROW,
              COMMAND_ITEM_FOCUS,
              "chat-command-palette-row cursor-pointer justify-between rounded-lg",
              selectedIndex === i ? "bg-control" : "hover:bg-muted",
            )}
          >
            <div className="min-w-0 flex-1">
              <p className="text-foreground font-mono text-xs">/{cmd.name}</p>
              <p className="text-muted-foreground truncate text-xs">{cmd.description}</p>
            </div>
            {cmd.aliases && cmd.aliases.length > 0 && (
              <span className="text-muted-foreground hidden font-mono text-xs sm:inline">
                /{cmd.aliases[0]}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
