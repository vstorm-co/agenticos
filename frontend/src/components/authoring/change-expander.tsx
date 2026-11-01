"use client";

import { useId, useState, type ReactNode } from "react";
import { Check, ChevronRight, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { badgeVariants } from "@/components/ui";
import { cn } from "@/lib/utils";

export type DecidedState = "accepted" | "edited" | "dismissed" | "created" | "notDecided";

/**
 * A decided change, folded to one line: what kind of change it is, how it was
 * decided and what it was for. Opening it shows the change itself, with Undo
 * where Undo still applies.
 */
export function ChangeExpander({
  label,
  state,
  summary,
  children,
}: {
  label: string;
  state: DecidedState;
  summary: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const body = useId();
  return (
    <div className="rounded-md border" data-testid="decided-change">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={body}
        onClick={() => setOpen(!open)}
        className="hover:bg-muted/50 flex w-full flex-wrap items-center gap-2 rounded-md px-3 py-2 text-left text-sm"
      >
        <ChevronRight
          className={cn("h-4 w-4 shrink-0 transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <span className="font-medium break-words">{label}</span>
        <StateBadge state={state} />
        {summary !== "" && (
          <span className="text-muted-foreground w-full pl-6 break-words">{summary}</span>
        )}
      </button>
      {open && (
        <div id={body} className="border-t p-3">
          {children}
        </div>
      )}
    </div>
  );
}

function StateBadge({ state }: { state: DecidedState }) {
  const t = useTranslations("authoring.tabs.state");
  const taken = state === "accepted" || state === "edited" || state === "created";
  const Icon = taken ? Check : X;
  return (
    <span className={badgeVariants({ variant: taken ? "success" : "secondary" })}>
      {state !== "notDecided" && (
        <Icon
          className={cn("h-3 w-3", taken ? "text-success" : "text-muted-foreground")}
          aria-hidden
        />
      )}
      {t(state)}
    </span>
  );
}
