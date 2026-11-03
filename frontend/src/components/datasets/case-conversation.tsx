"use client";

import { BookCheck, Bot, ChevronRight, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { cn } from "@/lib/utils";
import type { DatasetCaseContent } from "@/types/datasets";

/** Transcript styling from chat, without attributing a saved case to its reader. */
function CaseTurn({
  kind,
  label,
  text,
}: {
  kind: "user" | "assistant" | "reference";
  label: string;
  text: string;
}) {
  const user = kind === "user";
  const Icon = user ? UserRound : kind === "reference" ? BookCheck : Bot;
  return (
    <li className={cn("flex min-w-0 flex-col gap-2", user && "items-end")}>
      <div className={cn("flex items-center gap-2", user && "flex-row-reverse")}>
        <span
          className="bg-muted text-muted-foreground grid size-7 shrink-0 place-items-center rounded-full"
          aria-hidden
        >
          <Icon className="size-4" />
        </span>
        <h3 className="text-sm font-medium">{label}</h3>
      </div>
      {user ? (
        <div className="bg-foreground/[0.07] max-w-[92%] rounded-2xl px-4 py-2.5 text-sm break-words whitespace-pre-wrap">
          {text}
        </div>
      ) : (
        <div className="prose-sm w-full min-w-0 text-[15px] leading-relaxed wrap-anywhere">
          <MarkdownContent content={text} inertImages />
        </div>
      )}
    </li>
  );
}

/** A reference is an expectation, explicitly labelled rather than posed as a recorded answer. */
export function CaseConversation({
  content,
}: {
  content: Pick<DatasetCaseContent, "history" | "input" | "reference_answer">;
}) {
  const t = useTranslations("datasets");
  return (
    <section aria-label={t("conversationTitle")} className="space-y-6">
      {content.history.length > 0 && (
        <details className="group border-border border-b pb-4">
          <summary className="text-muted-foreground flex min-h-11 cursor-pointer items-center gap-2 text-sm">
            <ChevronRight className="size-4 transition-transform group-open:rotate-90" />
            {t("turnsBefore", { count: content.history.length })}
          </summary>
          <ol className="space-y-7 py-5">
            {content.history.map((turn, index) => (
              <CaseTurn
                key={index}
                kind={turn.role}
                label={t(`role.${turn.role}`)}
                text={turn.content}
              />
            ))}
          </ol>
        </details>
      )}
      <ol className="space-y-7">
        <CaseTurn kind="user" label={t("field.input")} text={content.input} />
        {content.reference_answer && (
          <CaseTurn
            kind="reference"
            label={t("field.reference_answer")}
            text={content.reference_answer}
          />
        )}
      </ol>
    </section>
  );
}
