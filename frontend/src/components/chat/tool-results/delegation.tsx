"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { cn } from "@/lib/utils";

import { MarkdownContent } from "../markdown-content";

/**
 * A delegation, after the fact: what the agent was asked, and what it answered.
 *
 * The brief first and quiet, because it is the parent's words and usually long -
 * folded to a few lines until somebody wants all of it. The answer is the
 * delegate's own and is drawn as the markdown it wrote.
 */
export function DelegationResult({ brief, answer }: { brief: string | null; answer: string }) {
  const t = useTranslations("chat.tools");
  const tChat = useTranslations("chat");
  const [briefOpen, setBriefOpen] = useState(false);
  return (
    <div className="space-y-3">
      {brief && (
        <div className="bg-foreground/[0.03] rounded-xl px-3 py-2.5">
          <p className="text-muted-foreground mb-1 text-[11px] font-medium tracking-wide uppercase">
            {t("delegationBrief")}
          </p>
          <p
            className={cn(
              "text-foreground/75 text-[13px] leading-relaxed whitespace-pre-line",
              !briefOpen && "line-clamp-3",
            )}
          >
            {brief}
          </p>
          <button
            type="button"
            onClick={() => setBriefOpen(!briefOpen)}
            className="text-muted-foreground hover:text-foreground mt-1 text-xs font-medium"
          >
            {briefOpen ? tChat("showLess") : tChat("showMore")}
          </button>
        </div>
      )}
      {answer && (
        <div className="border-foreground/10 rounded-xl border px-3.5 py-3 text-sm">
          <p className="text-muted-foreground mb-1.5 text-[11px] font-medium tracking-wide uppercase">
            {t("delegationAnswer")}
          </p>
          <MarkdownContent content={answer} inertImages />
        </div>
      )}
    </div>
  );
}
