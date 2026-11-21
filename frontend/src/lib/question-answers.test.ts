import { expect, it } from "vitest";
import { questionAnswerResult } from "./question-answers";
it("keeps selected, typed and declined answers in the replay format", () => {
  const questions = ["Choice", "Typed", "Skip", "Missing"].map((header) => ({
    header,
    question: header,
    options: [],
    allowCustom: true,
  }));
  expect(
    JSON.parse(
      questionAnswerResult(questions, [
        { answer: "", selected: ["List"], skipped: false },
        { answer: "Short", skipped: false },
        { answer: "", skipped: true },
      ]),
    ),
  ).toEqual({ Choice: ["List"], Typed: "Short", Skip: "(skipped)", Missing: "(skipped)" });
});

it("uses the question when there is no header", () => {
  expect(
    JSON.parse(
      questionAnswerResult(
        [{ question: "Format?", options: [], allowCustom: true }],
        [{ answer: "List", skipped: false }],
      ),
    ),
  ).toEqual({ "Format?": "List" });
});
