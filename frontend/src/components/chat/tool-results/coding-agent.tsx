"use client";

import {
  CircleAlert,
  FileText,
  Globe,
  PencilLine,
  Search,
  SquareTerminal,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";

import type { ToolCall } from "@/types";
import { cn } from "@/lib/utils";
import { CollapsibleBlock } from "../collapsible-block";
import { MarkdownContent } from "../markdown-content";

type StepKind = "read" | "search" | "edit" | "command" | "web" | "other";

interface CodingStep {
  kind: StepKind;
  title: string;
  failed?: boolean;
}

/** What `run_coding_agent` returns - `CodingReport` in the backend. */
interface CodingReport {
  kind: "coding_agent";
  harness: "claude_code" | "codex";
  access: "edit" | "read_only";
  outcome: "completed" | "failed" | "timed_out";
  answer: string;
  session_id?: string;
  steps?: CodingStep[];
  files_changed?: string[];
  refused?: string[];
}

const STEP_ICON: Record<StepKind, LucideIcon> = {
  read: FileText,
  search: Search,
  edit: PencilLine,
  command: SquareTerminal,
  web: Globe,
  other: Wrench,
};

/** The product's own names, which no locale translates. */
export const HARNESS_NAME: Record<CodingReport["harness"], string> = {
  // i18n-exempt: a product's own name
  claude_code: "Claude Code",
  // i18n-exempt: a product's own name
  codex: "Codex",
};

export function parseCodingReport(text: string): CodingReport | null {
  try {
    const parsed: unknown = JSON.parse(text);
    if (typeof parsed !== "object" || parsed === null) return null;
    if ("kind" in parsed) return parsed.kind === "coding_agent" ? (parsed as CodingReport) : null;
    // Reports stored before `kind` reached the wire carry no kind at all: they
    // are told apart by the two fields every report has.
    if ("harness" in parsed && "outcome" in parsed) {
      return { ...(parsed as Omit<CodingReport, "kind">), kind: "coding_agent" };
    }
  } catch {
    // A refusal - no sandbox, the harness not installed - is a sentence, not a report.
  }
  return null;
}

/**
 * What the coding agent was asked, what it answered, and every file it read or
 * changed and command it ran - the part a person checks before trusting the answer.
 */
export function CodingAgentResult({
  toolCall,
  resultText,
}: {
  toolCall: ToolCall;
  resultText: string;
}) {
  const t = useTranslations("chat.tools.codingAgent");
  const task = typeof toolCall.args?.task === "string" ? toolCall.args.task : null;
  const report = parseCodingReport(resultText);

  return (
    <div className="space-y-2 pt-1">
      {task !== null && (
        <CollapsibleBlock label={t("task")} copyText={task} open={report === null}>
          <p className="text-foreground/85 p-3 text-sm whitespace-pre-wrap">{task}</p>
        </CollapsibleBlock>
      )}
      {report === null ? (
        resultText !== "" && (
          <p className="text-muted-foreground py-2 text-xs italic">{resultText}</p>
        )
      ) : (
        <Report report={report} />
      )}
    </div>
  );
}

function Report({ report }: { report: CodingReport }) {
  const t = useTranslations("chat.tools.codingAgent");
  const steps = report.steps ?? [];
  const files = report.files_changed ?? [];
  const refused = report.refused ?? [];
  return (
    <>
      <div className="flex items-center gap-2 text-xs">
        <span className="text-foreground font-medium">{HARNESS_NAME[report.harness]}</span>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 font-medium",
            report.outcome === "completed"
              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
              : "bg-destructive/10 text-destructive",
          )}
        >
          {t("outcome", { outcome: report.outcome })}
        </span>
      </div>
      <div className="text-sm">
        <MarkdownContent content={report.answer} />
      </div>
      {files.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">
            {t("filesChanged", { count: files.length })}
          </span>
          {files.map((file) => (
            <span key={file} className="bg-foreground/[0.06] rounded px-1.5 py-0.5 font-mono">
              {file}
            </span>
          ))}
        </div>
      )}
      {steps.length > 0 && (
        <CollapsibleBlock label={t("steps", { count: steps.length })} open={false}>
          <ol className="max-h-80 scrollbar-thin space-y-1 overflow-y-auto p-3">
            {steps.map((step, index) => {
              const Icon = step.failed ? CircleAlert : STEP_ICON[step.kind];
              return (
                <li key={index} className="flex min-w-0 items-start gap-2 text-xs">
                  <Icon
                    className={cn(
                      "mt-0.5 size-3.5 shrink-0",
                      step.failed ? "text-destructive" : "text-muted-foreground",
                    )}
                    aria-label={t("stepKind", { kind: step.failed ? "failed" : step.kind })}
                  />
                  <span className="text-foreground/85 min-w-0 font-mono break-all">
                    {step.title}
                  </span>
                </li>
              );
            })}
          </ol>
        </CollapsibleBlock>
      )}
      {refused.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("refused", { tools: refused.join(", ") })}
        </p>
      )}
    </>
  );
}
