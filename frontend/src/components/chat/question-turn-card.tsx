"use client";

import { useLayoutEffect, useRef } from "react";
import { ChevronDown, MessageCircleQuestion } from "lucide-react";
import { useTranslations } from "next-intl";
import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { QuestionPrompt } from "@/components/ui/question-prompt";
import type { ToolCall } from "@/types";
import type { QuestionInteraction } from "./question-interaction";
import { AskedResult, parseAsked, type AskedQuestion } from "./tool-results/asked";
import { ToolCallCard } from "./tool-call-card";

/** The same surface owns waiting, submission and the persisted answer receipt. */
export function QuestionTurnCard({
  calls,
  interaction,
  answered,
  askedBy,
}: {
  calls: ToolCall[];
  interaction?: QuestionInteraction | null;
  answered?: AskedQuestion[];
  askedBy?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef(false);
  const wasInteractive = useRef(!!interaction);
  useLayoutEffect(() => {
    if (
      wasInteractive.current &&
      !interaction &&
      restoreFocus.current &&
      document.activeElement === document.body
    )
      root.current?.querySelector("summary")?.focus({ preventScroll: true });
    wasInteractive.current = !!interaction;
  }, [interaction]);
  const t = useTranslations("chat.questions");
  const tools = useTranslations("chat.tools");
  const chat = useTranslations("chat");
  const ui = useTranslations("ui");
  const asked = answered ?? calls.flatMap((call) => parseAsked(call) ?? []);
  if (asked.length === 0 && !interaction)
    return (
      <>
        {calls.map((call) => (
          <ToolCallCard key={call.id} toolCall={call} mcpServers={[]} />
        ))}
      </>
    );
  const title =
    calls.length === 0 && !interaction
      ? askedBy
        ? chat("askUserAskedBy", { name: askedBy })
        : chat("askUserAsked")
      : t(interaction ? "heading" : "answered");
  const heading = (
    <span className="flex items-center gap-2 text-sm font-medium">
      <MessageCircleQuestion className="text-muted-foreground size-4 shrink-0" aria-hidden />
      <span>{title}</span>
    </span>
  );
  return (
    <div
      ref={root}
      data-chat-question
      data-chat-anchor={calls[0]?.id ?? interaction?.id ?? "question-receipt"}
      data-question-pending={!!interaction || undefined}
      className="border-border bg-card my-3 w-full min-w-0 rounded-2xl border"
    >
      {interaction ? (
        <>
          <div className="flex items-center gap-2 px-4 pt-3 pb-2">
            {heading}
            {interaction.submitting && (
              <span role="status" className="text-muted-foreground ml-auto text-xs">
                {t("submitting")}
              </span>
            )}
          </div>
          <div className="max-h-[min(32rem,65dvh)] overflow-y-auto overscroll-contain px-1 pb-1">
            <QuestionPrompt
              embedded
              autoFocus={false}
              questions={interaction.questions}
              disabled={interaction.disabled || interaction.submitting}
              onComplete={(answers) => {
                restoreFocus.current = !!root.current?.contains(document.activeElement);
                interaction.onAnswer(answers);
              }}
            />
          </div>
        </>
      ) : (
        <NativeDisclosure className="group/question">
          <summary className="focus-visible:outline-ring cursor-pointer list-none rounded-2xl px-4 py-3 [&::-webkit-details-marker]:hidden">
            <span className="flex items-center justify-between gap-3">
              {heading}
              <ChevronDown
                className="text-muted-foreground size-4 shrink-0 transition-transform group-open/question:rotate-180 motion-reduce:transition-none"
                aria-hidden
              />
            </span>
            <span className="mt-2 grid min-w-0 gap-1 pl-6 text-sm">
              {asked.slice(0, 2).map((item, index) => (
                <span key={index} className="line-clamp-1 break-words">
                  <span className="text-muted-foreground">{item.header || item.question}: </span>
                  {item.answer === null
                    ? tools("notAnsweredYet")
                    : item.answer.length === 0
                      ? ui("skipped")
                      : item.answer.join(", ")}
                </span>
              ))}
            </span>
          </summary>
          <div className="border-border/60 border-t px-4 py-3">
            <AskedResult asked={asked} />
          </div>
        </NativeDisclosure>
      )}
      {calls.length > 0 && (
        <NativeDisclosure className="border-border/60 border-t px-4 py-2">
          <summary className="text-muted-foreground focus-visible:outline-ring cursor-pointer text-xs">
            {t("details")}
          </summary>
          <div className="pt-2">
            {calls.map((call) => (
              <ToolCallCard key={call.id} toolCall={call} mcpServers={[]} />
            ))}
          </div>
        </NativeDisclosure>
      )}
    </div>
  );
}
