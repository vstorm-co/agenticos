/**
 * An agent's questions, from the server's shape to the question card's (#2064).
 *
 * One mapping for the two ways they arrive: the live `ask_user` frame, and a run
 * parked on a question somebody left unanswered, read back when they return.
 */

import type { AskUserQuestion } from "@/types/chat";
import type { WireQuestion } from "@/types/runs";

export function toAskUserQuestions(
  questions: WireQuestion[],
  requestId?: string,
): AskUserQuestion[] {
  return questions.map((question) => ({
    question: question.question,
    ...(requestId ? { requestId } : {}),
    ...(typeof question.multiline === "boolean" ? { multiline: question.multiline } : {}),
    ...(typeof question.initial_value === "string" ? { initialValue: question.initial_value } : {}),
    ...(typeof question.allow_empty === "boolean" ? { allowEmpty: question.allow_empty } : {}),
    ...(typeof question.max_answer_length === "number"
      ? { maxAnswerLength: question.max_answer_length }
      : {}),
    header: question.header,
    options: (question.options ?? []).map((option) =>
      option.label_key ? { ...option, labelKey: option.label_key } : option,
    ),
    multiSelect: question.multi_select ?? false,
    ...(typeof question.min_selections === "number"
      ? { minSelections: question.min_selections }
      : {}),
    ...(typeof question.max_selections === "number"
      ? { maxSelections: question.max_selections }
      : {}),
    allowCustom: question.allow_custom,
  }));
}
