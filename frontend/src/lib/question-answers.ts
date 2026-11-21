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

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function resultRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "string") {
    try {
      const parsed: unknown = JSON.parse(value);
      return record(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }
  return record(value) ? value : null;
}

function actualAnswer(value: unknown): boolean {
  return (
    (typeof value === "string" && value.trim() !== "") ||
    (Array.isArray(value) && value.every((item: unknown) => typeof item === "string"))
  );
}

/** A partial result is not a retraction of answers already acknowledged for this call. */
export function retainQuestionAnswerResult(
  args: Record<string, unknown>,
  previous: unknown,
  incoming: unknown,
): unknown {
  const before = resultRecord(previous);
  const after = resultRecord(incoming);
  if (!before || after?.cancelled === true || !Array.isArray(args.questions)) return incoming;
  const retained: Record<string, unknown> = {};
  for (const question of args.questions) {
    if (!record(question) || typeof question.question !== "string") continue;
    const key = typeof question.header === "string" ? question.header : question.question;
    const answer = before.cancelled === true ? "(skipped)" : before[key];
    if (actualAnswer(answer) && !actualAnswer(after?.[key])) retained[key] = answer;
  }
  if (Object.keys(retained).length === 0) return incoming;
  const merged = { ...after, ...retained };
  return typeof incoming === "string" ? JSON.stringify(merged) : merged;
}
