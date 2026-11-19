"use client";

import { useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { ChevronRight, Plus, SlidersHorizontal, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

const NARROW_QUERY = "(max-width: 767px)";
function subscribeViewport(changed: () => void): () => void {
  const query = window.matchMedia(NARROW_QUERY);
  query.addEventListener("change", changed);
  return () => query.removeEventListener("change", changed);
}
const narrowViewport = () => window.matchMedia(NARROW_QUERY).matches;
const serverViewport = () => false;

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
  const narrow = useSyncExternalStore(subscribeViewport, narrowViewport, serverViewport);
  const input = useTranslations("chat.input");
  const common = useTranslations("common");
  const [open, setOpen] = useState(false);
  const morePanel = useRef<HTMLDivElement>(null);
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
        data-chat-popover
        aria-label={input("addToMessage")}
        side="bottom"
        align="start"
        sideOffset={8}
        collisionPadding={12}
        className="w-64 max-w-[calc(100vw-1.5rem)] rounded-2xl p-1.5"
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
        {children && (
          <div className="border-border mt-1 border-t pt-1">
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="hover:bg-muted focus-visible:bg-muted flex min-h-10 w-full items-center gap-3 rounded-xl px-3 py-2 text-sm outline-none"
                >
                  <SlidersHorizontal className="text-muted-foreground size-4" aria-hidden />
                  {common("showMore")}
                  <ChevronRight className="text-muted-foreground ml-auto size-3.5" aria-hidden />
                </button>
              </PopoverTrigger>
              <PopoverContent
                ref={morePanel}
                tabIndex={-1}
                onOpenAutoFocus={(event) => {
                  // Call availability explains itself on focus; opening More must
                  // not open that additional panel before a person reaches it.
                  event.preventDefault();
                  morePanel.current?.focus();
                }}
                data-chat-popover
                aria-label={common("showMore")}
                side={narrow ? "top" : "right"}
                align="start"
                sideOffset={12}
                collisionPadding={12}
                className="max-h-[min(480px,var(--radix-popover-content-available-height))] w-80 max-w-[calc(100vw-1.5rem)] overflow-y-auto rounded-2xl p-2"
              >
                {children}
              </PopoverContent>
            </Popover>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
