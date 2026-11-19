"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { DisclosureContent } from "./disclosure-content";
import { DISCLOSURE_TRIGGER } from "./control-styles";
import { cn } from "@/lib/utils";

/**
 * The settings a form does not need to be filled in, folded under one line.
 *
 * A create dialog asks for what the thing needs to exist; the rest - a note,
 * a reaction, how answers are drawn - waits here, closed, so the dialog is as
 * short as its required fields. One component, so every dialog folds the same
 * way and says so in the same words.
 */
export function MoreOptions({
  label,
  defaultOpen = false,
  open: controlled,
  onOpenChange,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  /** Held by the caller, for a fold that has to open itself - see `onOpenChange`. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
}) {
  const id = useId();
  const [own, setOwn] = useState(defaultOpen);
  const open = controlled ?? own;
  const toggle = () => {
    setOwn(!open);
    onOpenChange?.(!open);
  };
  return (
    <div>
      <button
        id={`${id}-toggle`}
        type="button"
        aria-controls={id}
        aria-expanded={open}
        onClick={toggle}
        className={cn(DISCLOSURE_TRIGGER, "border-t pt-3")}
      >
        <ChevronRight
          className={cn(
            "h-4 w-4 transition-transform motion-reduce:transition-none",
            open && "rotate-90",
          )}
          aria-hidden
        />
        {label}
      </button>
      <DisclosureContent
        id={id}
        open={open}
        triggerId={`${id}-toggle`}
        onReveal={() => {
          setOwn(true);
          onOpenChange?.(true);
        }}
      >
        <div className="space-y-4 pt-3">{children}</div>
      </DisclosureContent>
    </div>
  );
}
