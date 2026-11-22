import { expect, it } from "vitest";
import { questionAnswerResult, retainQuestionAnswerResult } from "./question-answers";
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

const args = {
  questions: [
    { header: "Day", question: "Which day?" },
    { header: "Format", question: "Which format?" },
  ],
};
const acknowledged = JSON.stringify({ Day: ["Thursday"], Format: ["Short"] });
it.each(["{}", "not a result", { Day: null, Format: "" }, { Day: [42] }, null])(
  "retains acknowledged selections over an incomplete receipt %j",
  (incoming) => {
    const kept = retainQuestionAnswerResult(args, acknowledged, incoming);
    expect(typeof kept === "string" ? JSON.parse(kept) : kept).toMatchObject({
      Day: ["Thursday"],
      Format: ["Short"],
    });
  },
);
it("accepts explicit server corrections and skips instead of freezing local choices", () => {
  for (const incoming of [
    { Day: ["Friday"], Format: "(skipped)" },
    { Day: [], Format: "Short" },
    { cancelled: true },
  ]) {
    expect(retainQuestionAnswerResult(args, acknowledged, incoming)).toEqual(incoming);
  }
});
it("preserves genuinely unanswered questions when no acknowledged value exists", () => {
  expect(retainQuestionAnswerResult(args, undefined, "{}")).toBe("{}");
  expect(retainQuestionAnswerResult({ questions: [] }, acknowledged, "{}")).toBe("{}");
  expect(retainQuestionAnswerResult({}, acknowledged, "{}")).toBe("{}");
});
it("retains a prior explicit skip over missing result fields without confusing it with unanswered", () => {
  expect(retainQuestionAnswerResult(args, { cancelled: true }, {})).toEqual({
    Day: "(skipped)",
    Format: "(skipped)",
  });
});

it.each([undefined, "invalid", "[]", 42])(
  "does not invent a receipt from an invalid prior result %j",
  (previous) => {
    expect(retainQuestionAnswerResult(args, previous, "{}")).toBe("{}");
  },
);
it("ignores malformed question entries and falls back to full question keys", () => {
  expect(
    retainQuestionAnswerResult(
      { questions: [null, {}, 42, { question: "Which day?" }] },
      { "Which day?": "Thursday" },
      "{}",
    ),
  ).toBe(JSON.stringify({ "Which day?": "Thursday" }));
});
