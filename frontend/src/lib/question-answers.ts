import type { AskUserAnswer, AskUserQuestion } from "@/types/chat";

/** The acknowledged selection, in the same header-keyed format as stored results. */
export function questionAnswerResult(
  questions: readonly AskUserQuestion[],
  answers: readonly AskUserAnswer[],
): string {
  return JSON.stringify(
    Object.fromEntries(
      questions.map((question, index) => {
        const answer = answers[index];
        return [
          question.header ?? question.question,
          !answer || answer.skipped
            ? "(skipped)"
            : answer.selected?.length
              ? answer.selected
              : answer.answer,
        ];
      }),
    ),
  );
}
