"use client";

import { useTranslations } from "next-intl";

import { Sheet, SheetClose, SheetContent } from "@/components/ui";
import type { DelegateRef } from "@/lib/delegations";
import { delegationStep } from "@/lib/tool-steps";
import { cn } from "@/lib/utils";
import type { DelegationStatus, DelegationStep } from "@/types";

import { AgentStep } from "./agent-step";
import { DelegateFace as Face } from "./delegate-face";
import { MarkdownContent } from "./markdown-content";

/** The catalog key for each status, translated at the point of use. */
export const STATUS_KEY: Record<DelegationStatus, string> = {
  running: "working",
  completed: "finished",
  failed: "failed",
  cancelled: "stopped",
  awaiting_approval: "awaiting",
};

/** One delegation as the sheet reads it, whether it is still out or long back. */
export interface SheetDelegation {
  key: string;
  delegate: DelegateRef;
  status: DelegationStatus;
  brief: string | null;
  answer: string;
  /** What the delegate did, where it is known - live, from its frames. */
  steps?: DelegationStep[];
}

/**
 * One delegation, read at the side: who was asked, what they were asked, what
 * they did and what they said - with the rest of the team along the top to move
 * between them.
 *
 * At the side rather than under the answer, where a brief and a long reply
 * pushed the answer itself off the screen.
 */
export function DelegationSheet({
  items,
  opened,
  onOpen,
  onClose,
}: {
  items: SheetDelegation[];
  opened: string;
  onOpen: (key: string) => void;
  onClose: () => void;
}) {
  const t = useTranslations("chat.delegation");
  const tTools = useTranslations("chat.tools");
  // `opened` is always one of `items`: every caller opens the sheet from one.
  const item = items.find((each) => each.key === opened)!;

  return (
    <Sheet open onOpenChange={onClose}>
      <SheetContent side="right" className="bg-background w-full sm:max-w-lg">
        <div className="flex items-center gap-2 border-b px-4 py-3">
          <div role="tablist" aria-label={t("teamOnThis")} className="flex min-w-0 flex-1 gap-1">
            {items.map((each) => (
              <button
                key={each.key}
                type="button"
                role="tab"
                aria-selected={each.key === item.key}
                title={each.delegate.name}
                aria-label={each.delegate.name}
                onClick={() => onOpen(each.key)}
                className={cn(
                  "rounded-full p-0.5 transition-opacity",
                  each.key === item.key
                    ? "ring-foreground/30 ring-2"
                    : "opacity-55 hover:opacity-100",
                )}
              >
                <Face who={each.delegate} className="h-7 w-7" />
              </button>
            ))}
          </div>
          <SheetClose onClick={onClose} />
        </div>

        <div className="flex items-center gap-3 px-5 pt-5">
          <Face who={item.delegate} className="h-10 w-10" />
          <div className="min-w-0">
            <h2 className="text-foreground truncate text-base font-semibold">
              {item.delegate.name}
            </h2>
            <p className="text-muted-foreground text-xs">
              {t(STATUS_KEY[item.status])}
              {item.steps && item.steps.length > 0 && (
                <> · {t("actionCount", { count: item.steps.length })}</>
              )}
            </p>
          </div>
        </div>

        <div className="min-h-0 flex-1 scrollbar-thin space-y-5 overflow-y-auto px-5 py-5">
          {item.brief && (
            <section className="space-y-1.5">
              <h3 className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
                {tTools("delegationBrief")}
              </h3>
              <p className="text-foreground/75 border-foreground/15 border-l-2 pl-3 text-[13px] leading-relaxed whitespace-pre-line">
                {item.brief}
              </p>
            </section>
          )}
          {item.steps && item.steps.length > 0 && (
            <section className="space-y-1.5">
              <h3 className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
                {t("actions")}
              </h3>
              <div>
                {item.steps.map((step) => {
                  // The frames carry no arguments and no result, so a step is a
                  // line and nothing opens under it.
                  const shown = delegationStep(step, tTools);
                  return (
                    <AgentStep
                      key={step.id}
                      label={shown.label}
                      detail={shown.detail}
                      kind={shown.kind}
                      state={step.ok === null ? "running" : step.ok ? "done" : "error"}
                      expanded={false}
                    />
                  );
                })}
              </div>
            </section>
          )}
          {item.answer && (
            <section className="space-y-1.5">
              <h3 className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
                {tTools("delegationAnswer")}
              </h3>
              <div className="text-sm">
                <MarkdownContent content={item.answer} inertImages />
              </div>
            </section>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
