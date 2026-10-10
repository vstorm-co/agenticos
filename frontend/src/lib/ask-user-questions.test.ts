import { describe, expect, it } from "vitest";

import { toAskUserQuestions } from "./ask-user-questions";

describe("toAskUserQuestions", () => {
  it("reads the server's questions into the card's shape", () => {
    expect(
      toAskUserQuestions([
        {
          question: "How formal?",
          header: "Tone",
          options: [{ label: "Formal", description: "For customers" }],
          multi_select: true,
          allow_custom: false,
        },
        { question: "Anything else?", allow_custom: true },
      ]),
    ).toEqual([
      {
        question: "How formal?",
        header: "Tone",
        options: [{ label: "Formal", description: "For customers" }],
        multiSelect: true,
        allowCustom: false,
      },
      {
        question: "Anything else?",
        header: undefined,
        options: [],
        multiSelect: false,
        allowCustom: true,
      },
    ]);
  });
});
