"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { answerPreview, delegateNamed, delegateOf, type DelegateRef } from "@/lib/delegations";
import { delegationStep } from "@/lib/tool-steps";
import { cn } from "@/lib/utils";
import type { Delegation } from "@/types";

import { DelegateFace as Face } from "./delegate-face";
import { DelegationSheet, STATUS_KEY } from "./delegation-sheet";

/**
 * The team talking it through, while it does: what the agent asked each
 * colleague, in its own words, and the colleague's reply arriving under it.
 *
 * A delegation is one agent passing work to another and getting an answer back,
 * so it is drawn as that exchange rather than as a stack of status panels. A
 * delegate at work hops and types; its reply reads as the first thing it said.
 * Everything it did - the steps, the whole answer - is a click away, at the side.
 */
export function DelegationChat({
  delegations,
  agents,
  parent,
}: {
  delegations: Delegation[];
  agents: readonly DelegateRef[];
  parent?: DelegateRef;
}) {
  const t = useTranslations("chat.delegation");
  const tTools = useTranslations("chat.tools");
  const [opened, setOpened] = useState<string | null>(null);
  const asker = parent ?? delegateNamed("agent", agents);
  const items = delegations.map((delegation) => ({
    key: delegation.taskId,
    delegate: delegateOf(delegation, agents),
    status: delegation.status,
    brief: delegation.prompt,
    answer: delegation.text,
    steps: delegation.steps,
  }));

  return (
    <div className="space-y-3 pb-2" role="log" aria-label={t("teamAtWork")}>
      {items.map((item, beat) => {
        const working = item.status === "running";
        const preview = answerPreview(item.answer);
        // What it is doing this moment, while it works and has said so - a coding
        // harness names every file it reads and command it runs.
        const latest = item.steps.at(-1);
        const doing =
          working && latest !== undefined && latest.title !== null
            ? delegationStep(latest, tTools)
            : null;
        return (
          <div key={item.key} className="step-in space-y-1.5">
            <div className="flex items-start gap-2">
              <Face who={asker} className="h-6 w-6" />
              <div className="min-w-0">
                <p className="text-muted-foreground text-[11px]">
                  {t("askedBy", { from: asker.name, to: item.delegate.name })}
                </p>
                <p className="bg-foreground/[0.05] text-foreground/85 line-clamp-2 max-w-xl rounded-[4px_14px_14px_14px] px-3 py-1.5 text-[13px] leading-relaxed">
                  {item.brief}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setOpened(item.key)}
              className="group/reply flex max-w-full items-start gap-2 pl-6 text-left"
            >
              <span
                className={cn("relative shrink-0", working && "blob-hop")}
                style={working ? { animationDelay: `${beat * 0.18}s` } : undefined}
              >
                <Face who={item.delegate} thinking={working} className="h-6 w-6" />
                {item.status === "completed" && (
                  <span className="bg-success ring-background absolute -right-0.5 -bottom-0.5 grid size-3 place-items-center rounded-full ring-2">
                    <Check className="text-background h-2 w-2" strokeWidth={3} aria-hidden />
                  </span>
                )}
              </span>
              <span className="min-w-0">
                <span className="text-muted-foreground block text-[11px]">
                  {item.delegate.name} · {t(STATUS_KEY[item.status])}
                  {item.steps.length > 0 && (
                    <> · {t("actionCount", { count: item.steps.length })}</>
                  )}
                </span>
                {doing !== null && (
                  <span className="text-muted-foreground mb-1 block max-w-xl truncate font-mono text-[11px]">
                    {doing.label} {doing.detail}
                  </span>
                )}
                <span className="bg-foreground/[0.05] group-hover/reply:bg-foreground/[0.08] block max-w-xl rounded-[4px_14px_14px_14px] px-3 py-1.5 text-[13px] leading-relaxed transition-colors">
                  {preview !== "" ? (
                    <span className="text-foreground/85 line-clamp-2">{preview}</span>
                  ) : (
                    <span className="typing-dots" aria-label={t(STATUS_KEY[item.status])}>
                      <i />
                      <i />
                      <i />
                    </span>
                  )}
                </span>
              </span>
            </button>
          </div>
        );
      })}
      {opened !== null && (
        <DelegationSheet
          items={items}
          opened={opened}
          onOpen={setOpened}
          onClose={() => setOpened(null)}
        />
      )}
    </div>
  );
}
