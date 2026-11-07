"use client";

import { ChevronRight, Wrench } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { describeCheck } from "@/lib/scoring";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { CaseConversation } from "./case-conversation";
import type { DatasetCaseContent } from "@/types/datasets";

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="space-y-3 border-t pt-5">
      <h3 className="text-sm font-medium">{label}</h3>
      {children}
    </section>
  );
}

/**
 * A case as it reads: the conversation up to the input as bubbles, what a good
 * and a bad answer are, the tools and the checks, and its labels.
 */
export function CaseView({ content }: { content: DatasetCaseContent & { masked?: boolean } }) {
  const t = useTranslations("datasets");
  if (content.masked)
    return <p className="text-muted-foreground text-sm">{t("maskedConversation")}</p>;
  return (
    <div className="min-w-0 space-y-7 wrap-anywhere">
      <CaseConversation content={content} />
      {content.counter_example && (
        <details className="group border-border border-t pt-4">
          <summary className="text-muted-foreground flex min-h-11 cursor-pointer items-center gap-2 text-sm font-medium">
            <ChevronRight className="size-4 transition-transform group-open:rotate-90" />
            {t("field.counter_example")}
          </summary>
          <div className="pt-3 text-sm">
            <MarkdownContent content={content.counter_example} inertImages />
          </div>
        </details>
      )}
      {content.expected_tool_calls.length > 0 && (
        <Section
          label={`${t("field.expected_tool_calls")} · ${t(`orderMode.${content.order_mode}`)}`}
        >
          <div className="space-y-2">
            {content.expected_tool_calls.map((call, index) => (
              <details key={index} className="group border-border rounded-xl border">
                <summary className="flex cursor-pointer items-center gap-2 px-3 py-2.5 text-sm">
                  <ChevronRight className="text-muted-foreground size-3.5 shrink-0 transition-transform group-open:rotate-90" />
                  <Wrench className="text-muted-foreground size-3.5 shrink-0" />
                  <span className="min-w-0 font-medium break-all">{call.tool}</span>
                </summary>
                <pre className="bg-muted/40 overflow-x-auto border-t p-3 text-xs break-all whitespace-pre-wrap">
                  {JSON.stringify(call.args, null, 2)}
                </pre>
              </details>
            ))}
          </div>
        </Section>
      )}
      {content.checks.length > 0 && (
        <Section label={t("field.checks")}>
          <ul className="text-muted-foreground space-y-2 text-sm">
            {content.checks.map((check, index) => (
              <li key={index} className="break-all">
                {describeCheck(check)}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {content.note && (
        <Section label={t("field.note")}>
          <p className="text-sm whitespace-pre-wrap">{content.note}</p>
        </Section>
      )}
      {content.tags.length > 0 && (
        <Section label={t("field.tags")}>
          <div className="flex flex-wrap gap-1.5">
            {content.tags.map((tag) => (
              <Badge
                key={tag}
                variant="outline"
                className="max-w-full font-normal break-all whitespace-normal"
              >
                {tag}
              </Badge>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
