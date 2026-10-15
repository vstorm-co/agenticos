"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { describeCheck } from "@/lib/scoring";
import { cn } from "@/lib/utils";
import type { DatasetCaseContent } from "@/types/datasets";

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-muted-foreground text-xs font-medium">{label}</h3>
      {children}
    </section>
  );
}

/** One turn as a chat bubble: the person on the right, the agent on the left. */
function Bubble({ speaker, children }: { speaker: "user" | "assistant"; children: ReactNode }) {
  const t = useTranslations("datasets");
  return (
    <div className={cn("flex", speaker === "user" ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3 py-2 text-sm break-words whitespace-pre-wrap",
          speaker === "user" ? "bg-primary/10" : "bg-muted",
        )}
      >
        <span className="text-muted-foreground block text-[10px] font-medium uppercase">
          {t(`role.${speaker}`)}
        </span>
        {children}
      </div>
    </div>
  );
}

/**
 * A case as it reads: the conversation up to the input as bubbles, what a good
 * and a bad answer are, the tools and the checks, and its labels.
 */
export function CaseView({ content }: { content: DatasetCaseContent }) {
  const t = useTranslations("datasets");
  return (
    <div className="space-y-5">
      <Section label={t("field.input")}>
        <div className="space-y-2">
          {content.history.map((turn, index) => (
            <Bubble key={index} speaker={turn.role}>
              {turn.content}
            </Bubble>
          ))}
          <Bubble speaker="user">{content.input}</Bubble>
        </div>
      </Section>
      {content.reference_answer && (
        <Section label={t("field.reference_answer")}>
          <p className="text-sm whitespace-pre-wrap">{content.reference_answer}</p>
        </Section>
      )}
      {content.counter_example && (
        <Section label={t("field.counter_example")}>
          <p className="text-sm whitespace-pre-wrap">{content.counter_example}</p>
        </Section>
      )}
      {content.expected_tool_calls.length > 0 && (
        <Section
          label={`${t("field.expected_tool_calls")} · ${t(`orderMode.${content.order_mode}`)}`}
        >
          <ul className="font-mono text-xs">
            {content.expected_tool_calls.map((call, index) => (
              <li key={index} className="break-all">
                {call.tool}
                {Object.keys(call.args).length > 0 && ` ${JSON.stringify(call.args)}`}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {content.checks.length > 0 && (
        <Section label={t("field.checks")}>
          <ul className="font-mono text-xs">
            {content.checks.map((check, index) => (
              <li key={index} className="break-all">
                {describeCheck(check)}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {(content.tags.length > 0 || content.note) && (
        <Section label={t("field.note")}>
          {content.note && <p className="text-sm whitespace-pre-wrap">{content.note}</p>}
          <div className="flex flex-wrap gap-1.5">
            {content.tags.map((tag) => (
              <Badge key={tag} variant="outline" className="font-normal">
                {tag}
              </Badge>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
