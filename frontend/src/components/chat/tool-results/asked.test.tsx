import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../../messages/en.json";
import type { ToolCall } from "@/types";

import { AskedResult, parseAsked } from "./asked";

function call(result: unknown): ToolCall {
  return {
    id: "c1",
    name: "ask_user_question",
    status: result === undefined ? "awaiting_answer" : "completed",
    args: {
      questions: [
        { header: "Chart style", question: "How do you want it shown?", options: [] },
        { header: "Plans to include", question: "Which plans?", options: [] },
        { question: "Anything else?" },
        "not a question",
      ],
    },
    result,
  } as unknown as ToolCall;
}

describe("what an ask_user_question step shows", () => {
  it("pairs each question with the labels chosen, read from the stored JSON", () => {
    const asked = parseAsked(
      call(
        JSON.stringify({
          "Chart style": ["Lines"],
          "Plans to include": ["Starter", "Growth"],
          "Anything else?": " Keep it short ",
        }),
      ),
    );

    expect(asked).toEqual([
      { header: "Chart style", question: "How do you want it shown?", answer: ["Lines"] },
      { header: "Plans to include", question: "Which plans?", answer: ["Starter", "Growth"] },
      { header: "", question: "Anything else?", answer: ["Keep it short"] },
    ]);
  });

  it("says a question is still open while the run waits on it", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <AskedResult asked={parseAsked(call(undefined))!} />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("How do you want it shown?")).toBeInTheDocument();
    expect(screen.getAllByText("Not answered yet")).toHaveLength(3);
  });

  it("is not a question list when the arguments carry none", () => {
    expect(parseAsked({ ...call({}), args: {} } as ToolCall)).toBeNull();
    expect(parseAsked(call("not json"))?.every((item) => item.answer === null)).toBe(true);
    expect(parseAsked(call({ "Chart style": "" }))?.[0]?.answer).toBeNull();
  });
});
