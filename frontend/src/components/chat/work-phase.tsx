"use client";

import type { ReactNode } from "react";
import {
  Check,
  ChevronRight,
  CircleAlert,
  Lightbulb,
  OctagonPause,
  ShieldCheck,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "./markdown-content";

export interface ReasoningSection {
  title?: string;
  body: string;
}

/** Only standalone Markdown headings name phases; prose and fenced examples stay intact. */
export function reasoningSections(text: string): ReasoningSection[] {
  const sections: ReasoningSection[] = [];
  let section: ReasoningSection = { body: "" };
  let fence: string | undefined;
  for (const line of text.split("\n")) {
    const boundary = /^\s{0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    const marker = boundary?.[1];
    if (marker) {
      if (!fence) fence = marker;
      else if (marker[0] === fence[0] && marker.length >= fence.length && !boundary?.[2]?.trim())
        fence = undefined;
      section.body += `${line}\n`;
      continue;
    }
    const heading = !fence ? /^(?:#{1,6}\s+(.+?)(?:\s+#+)?|\*\*([^*]+)\*\*)\s*$/.exec(line) : null;
    const title = (heading?.[1] ?? heading?.[2])?.trim();
    if (title && title.length <= 140) {
      if (section.title || section.body.trim())
        sections.push({ ...section, body: section.body.trim() });
      section = { title, body: "" };
    } else section.body += `${line}\n`;
  }
  if (section.title || section.body.trim())
    sections.push({ ...section, body: section.body.trim() });
  return sections;
}

/** A named stretch of reasoning and the tools it led to, collapsed until inspected. */
export function WorkPhase({
  title,
  body,
  steps,
  running,
  waiting,
  failed = false,
  stopped = false,
  children,
}: {
  title: string;
  body: string;
  steps: number;
  running: boolean;
  failed?: boolean;
  stopped?: boolean;
  waiting?: "awaiting_approval" | "awaiting_answer";
  children: ReactNode;
}) {
  const t = useTranslations("chat.steps");
  const runText = useTranslations("pages.runs");
  const Icon = failed
    ? CircleAlert
    : waiting
      ? ShieldCheck
      : stopped
        ? OctagonPause
        : running
          ? Lightbulb
          : Check;
  const status = failed ? "error" : (waiting ?? (stopped ? "unfinished" : undefined));
  return (
    <details className="group/phase min-w-0">
      <summary className="text-muted-foreground hover:text-foreground focus-visible:ring-ring flex min-h-9 cursor-pointer list-none items-center gap-2 rounded-lg py-1 text-[13px] outline-none focus-visible:ring-2 [&::-webkit-details-marker]:hidden">
        <span className="flex size-5 shrink-0 items-center justify-center" aria-hidden>
          <Icon className={cn("size-3.5", running && "animate-pulse")} />
        </span>
        <span className={cn("min-w-0 font-medium break-words", running && "shimmer-text")}>
          {title}
        </span>
        {status ? (
          <span className="text-info shrink-0 text-xs">{runText("toolState", { status })}</span>
        ) : steps > 0 ? (
          <span className="shrink-0 text-xs tabular-nums">
            {t("activityCount", { count: steps })}
          </span>
        ) : null}
        <ChevronRight
          aria-hidden
          className="size-3.5 shrink-0 opacity-50 transition-transform group-open/phase:rotate-90 motion-reduce:transition-none"
        />
      </summary>
      <div className="border-foreground/10 ml-2.5 space-y-2 border-l py-1 pl-4">
        {body && (
          <div className="text-muted-foreground text-[13px] leading-relaxed">
            <MarkdownContent content={body} />
          </div>
        )}
        {children}
      </div>
    </details>
  );
}
