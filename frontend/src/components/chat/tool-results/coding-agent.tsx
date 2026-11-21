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
import { z } from "zod";

import type { TurnFileSource } from "@/types/chat";
import { WorkspaceFileCard } from "./workspace";
import type { ToolCall } from "@/types";
import { cn } from "@/lib/utils";
import { CollapsibleBlock } from "../collapsible-block";
import { MarkdownContent } from "../markdown-content";
import { TaskChanges } from "./coding-changes";

const optionalText = z
  .string()
  .nullish()
  .transform((value) => value ?? undefined);
const codingStep = z.object({
  kind: z.enum(["read", "search", "edit", "command", "web", "other"]),
  title: z.string(),
  failed: z.boolean().optional(),
});

/** Owned fields of backend CodingReport, including reports stored before kind existed. */
const codingReport = z.object({
  kind: z.literal("coding_agent").default("coding_agent"),
  harness: z.enum(["claude_code", "codex", "custom"]),
  access: z.enum(["edit", "read_only"]),
  outcome: z.enum(["completed", "failed", "timed_out"]),
  answer: z.string(),
  session_id: optionalText,
  session_name: optionalText,
  session_resumed: z
    .boolean()
    .nullish()
    .transform((value) => value ?? undefined),
  steps: z.array(codingStep).optional(),
  files_changed: z.array(z.string()).optional(),
  refused: z.array(z.string()).optional(),
  changes_id: optionalText,
  runtime_name: optionalText,
  account_label: optionalText,
  base_revision: optionalText,
  result_archive: optionalText,
});

type CodingReport = z.infer<typeof codingReport>;
type StepKind = z.infer<typeof codingStep>["kind"];

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
  // i18n-exempt: protocol name
  custom: "ACP",
};

export function parseCodingReport(text: string): CodingReport | null {
  try {
    const parsed: unknown = JSON.parse(text);
    const report = codingReport.safeParse(parsed);
    return report.success ? report.data : null;
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
  fileSource,
}: {
  toolCall: ToolCall;
  resultText: string;
  fileSource?: TurnFileSource;
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
        <Report report={report} fileSource={fileSource} />
      )}
    </div>
  );
}

function Report({ report, fileSource }: { report: CodingReport; fileSource?: TurnFileSource }) {
  const personal = useTranslations("codingAccounts");
  const t = useTranslations("chat.tools.codingAgent");
  const steps = report.steps ?? [];
  const files = report.files_changed ?? [];
  const refused = report.refused ?? [];
  const names = files.length > 0 && (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-muted-foreground">{t("filesChanged", { count: files.length })}</span>
      {files.map((file) => (
        <span key={file} className="bg-foreground/[0.06] rounded px-1.5 py-0.5 font-mono">
          {file}
        </span>
      ))}
    </div>
  );
  return (
    <>
      <div className="flex items-center gap-2 text-xs">
        <span className="text-foreground font-medium">
          {typeof report.runtime_name === "string"
            ? report.runtime_name
            : HARNESS_NAME[report.harness]}
        </span>
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
      {typeof report.session_name === "string" &&
        /^[a-z0-9][a-z0-9_-]{0,39}$/.test(report.session_name) && (
          <p className="text-muted-foreground text-xs">
            {personal(
              typeof report.session_resumed === "boolean"
                ? report.session_resumed
                  ? "continuedSession"
                  : "newSession"
                : "sessionName",
              { name: report.session_name },
            )}
          </p>
        )}
      {typeof report.account_label === "string" && (
        <p className="text-muted-foreground text-xs">
          {personal("personalAccount", { label: report.account_label })}
        </p>
      )}
      {typeof report.base_revision === "string" && (
        <p className="text-muted-foreground text-xs">
          {personal("baseRevision", { revision: report.base_revision.slice(0, 12) })}
        </p>
      )}
      {typeof report.result_archive === "string" &&
        /^coding-results\/[a-f0-9-]{36}\.zip$/.test(report.result_archive) && (
          <WorkspaceFileCard fileSource={fileSource} path={report.result_archive} />
        )}
      {/* The diff, where one was kept, says everything the list of names did. */}
      {report.changes_id !== undefined ? (
        <TaskChanges
          changeId={report.changes_id}
          conversationId={fileSource?.kind === "conversation" ? fileSource.id : undefined}
        />
      ) : (
        names
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
