/**
 * An agent's questions, from the server's shape to the question card's (#2064).
 *
 * One mapping for the two ways they arrive: the live `ask_user` frame, and a run
 * parked on a question somebody left unanswered, read back when they return.
 */

import type { AskUserQuestion } from "@/types/chat";
import type { WireQuestion } from "@/types/runs";

export function toAskUserQuestions(questions: WireQuestion[]): AskUserQuestion[] {
  return questions.map((question) => ({
    question: question.question,
    header: question.header,
    options: question.options ?? [],
    multiSelect: question.multi_select ?? false,
    allowCustom: question.allow_custom,
  }));
}
