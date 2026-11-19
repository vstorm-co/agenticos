"use client";

import { useRef, useState, type ReactNode } from "react";
import { Plus, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

interface ComposerAction {
  key: string;
  icon: LucideIcon;
  label: string;
  run: () => void;
}

/** Secondary controls use a small anchored panel, not an always-visible toolbar. */
export function ChatComposerMenu({
  actions,
  disabled,
  children,
}: {
  actions: readonly ComposerAction[];
  disabled?: boolean;
  children?: ReactNode;
}) {
  const input = useTranslations("chat.input");
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={input("addToMessage")}
          className="chat-attach-trigger focus-visible:ring-ring hover:bg-muted grid size-9 shrink-0 place-items-center rounded-full outline-none focus-visible:ring-2"
        >
          <Plus className="size-5 transition-transform duration-150" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
        ref={panel}
        tabIndex={-1}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          panel.current?.focus();
        }}
        data-chat-popover
        aria-label={input("addToMessage")}
        side="bottom"
        align="start"
        sideOffset={8}
        collisionPadding={12}
        className="max-h-[min(480px,var(--radix-popover-content-available-height))] w-72 max-w-[calc(100vw-1.5rem)] overflow-y-auto rounded-2xl p-1.5"
        onInteractOutside={(event) => {
          if (
            document.querySelector(".driver-popover") ||
            (event.target instanceof Element &&
              event.target.closest("[data-coding-account-connect]"))
          )
            event.preventDefault();
        }}
      >
        {actions
          .filter((action) => action.key !== "voice")
          .map((action) => (
            <button
              type="button"
              key={action.key}
              className="hover:bg-muted focus-visible:bg-muted flex min-h-10 w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm outline-none"
              onClick={() => {
                setOpen(false);
                action.run();
              }}
            >
              <action.icon className="text-muted-foreground size-4 shrink-0" aria-hidden />
              {action.label}
            </button>
          ))}
        {children && <div className="border-border mt-1 border-t pt-1">{children}</div>}
      </PopoverContent>
    </Popover>
  );
}
