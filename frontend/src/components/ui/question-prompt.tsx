"use client";

import { useState } from "react";
import { ChevronLeft, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { Button } from "./button";
import {
  QuestionSlide,
  type QuestionPromptAnswer,
  type QuestionPromptItem,
} from "./question-slide";

export type { QuestionChoice, QuestionPromptAnswer, QuestionPromptItem } from "./question-slide";

export interface QuestionPromptProps {
  /** Questions to ask, in order. The card shows one at a time. */
  questions: QuestionPromptItem[];
  /** Disable all controls (e.g. while the socket is offline). */
  disabled?: boolean;
  /** Called once with an answer (or a skip) for every question. */
  onComplete: (answers: QuestionPromptAnswer[]) => void;
}

const SKIPPED: QuestionPromptAnswer = { answer: "", skipped: true };

function shown(answer: QuestionPromptAnswer | undefined, skipped: string): string {
  if (!answer || answer.skipped) return skipped;
  return answer.selected && answer.selected.length > 0 ? answer.selected.join(", ") : answer.answer;
}

/**
 * A carousel of questions the agent is waiting on (#2064).
 *
 * One question per slide, the way Claude's web app asks: a chip naming it, the
 * options as large rows with what each means, and a free answer underneath.
 * Picking moves on; the dots and Back revisit an earlier slide. With more than
 * one question the last step is a summary, so nothing is sent until the person
 * has seen all their answers together. × skips everything that is left, which
 * the agent reads as declining.
 */
export function QuestionPrompt({ questions, disabled = false, onComplete }: QuestionPromptProps) {
  const t = useTranslations("ui");
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<(QuestionPromptAnswer | undefined)[]>([]);
  // The furthest slide reached, so the dots can go forward again after Back.
  const [reached, setReached] = useState(0);

  const total = questions.length;
  if (total === 0) return null;
  const reviewing = step >= total;

  const answer = (index: number, given: QuestionPromptAnswer) => {
    const next = [...answers];
    next[index] = given;
    setAnswers(next);
    if (total === 1) {
      onComplete([given]);
      return;
    }
    setStep(index + 1);
    setReached(Math.max(reached, index + 1));
  };

  // Sending from the summary and × are the same act: whatever was not answered
  // goes back as skipped.
  const settle = () => onComplete(questions.map((_, index) => answers[index] ?? SKIPPED));

  return (
    <div className="bg-muted/40 border-foreground/10 overflow-hidden rounded-2xl border">
      <div className="flex items-center justify-between gap-3 px-4 pt-2.5 pb-2">
        <div className="flex items-center gap-2">
          {step > 0 && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => setStep(step - 1)}
              aria-label={t("previousQuestion")}
              className="text-muted-foreground hover:text-foreground -ml-1 rounded-md p-0.5"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
          )}
          {total > 1 && (
            <span className="text-muted-foreground font-mono text-[11px] tracking-wider uppercase">
              {reviewing ? t("reviewAnswers") : t("questionStep", { step: step + 1, total })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {total > 1 && (
            <div className="flex items-center gap-1">
              {questions.map((item, index) => (
                <button
                  key={`${item.header ?? item.question}-${index}`}
                  type="button"
                  disabled={disabled || index > reached}
                  onClick={() => setStep(index)}
                  aria-label={t("goToQuestion", { step: index + 1 })}
                  className={cn(
                    "h-1.5 rounded-full transition-all",
                    index === step
                      ? "bg-foreground w-4"
                      : answers[index]
                        ? "bg-foreground/50 w-1.5"
                        : "bg-foreground/15 w-1.5",
                  )}
                />
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={settle}
            disabled={disabled}
            aria-label={t("dismissQuestions")}
            className="text-muted-foreground hover:text-foreground shrink-0 rounded-md p-1 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {reviewing ? (
        <div className="space-y-3 px-4 pb-3">
          <dl className="space-y-2">
            {questions.map((item, index) => (
              <div key={`${item.header ?? item.question}-${index}`}>
                <dt className="text-muted-foreground text-xs">{item.header ?? item.question}</dt>
                <dd className="text-foreground text-sm">{shown(answers[index], t("skipped"))}</dd>
              </div>
            ))}
          </dl>
          <div className="flex justify-end">
            <Button type="button" size="sm" disabled={disabled} onClick={settle}>
              {t("sendAnswers")}
            </Button>
          </div>
        </div>
      ) : (
        <>
          <QuestionSlide
            key={step}
            item={questions[step]!}
            previous={answers[step]}
            disabled={disabled}
            onAnswer={(given) => answer(step, given)}
          />
          <div className="border-foreground/8 flex justify-end border-t px-4 py-2">
            <button
              type="button"
              disabled={disabled}
              onClick={() => answer(step, SKIPPED)}
              className="text-muted-foreground hover:text-foreground text-xs transition-colors"
            >
              {t("skip")}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
