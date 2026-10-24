import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CaseView } from "./case-view";
import { CriterionScope } from "./criterion-scope";

function Scope() {
  const [tags, setTags] = useState<string[]>([]);
  return (
    <CriterionScope
      tags={tags}
      groups={[
        { tags: ["billing", "returns"], cases: 2 },
        { tags: ["returns"], cases: 1 },
      ]}
      total={3}
      disabled={false}
      onChange={setTags}
    />
  );
}

describe("case privacy and criterion scope", () => {
  it("renders a privacy mask without exposing an old question or reference", () => {
    render(
      <CaseView
        content={{
          masked: true,
          input: "PRIVATE_INPUT",
          reference_answer: "PRIVATE_REFERENCE",
          history: [],
          counter_example: null,
          expected_tool_calls: [],
          order_mode: "any",
          checks: [],
          tags: [],
          note: null,
        }}
      />,
    );
    expect(screen.getByText("From a conversation you cannot open")).toBeInTheDocument();
    expect(screen.queryByText("PRIVATE_INPUT")).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE_REFERENCE")).not.toBeInTheDocument();
  });
  it("switches between all cases and tags and counts overlap once", async () => {
    render(<Scope />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Every case" }));
    expect(screen.getByRole("checkbox", { name: "billing" })).toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "returns" }));
    expect(screen.getByRole("checkbox", { name: "billing" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "returns" })).toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "billing" }));
    expect(screen.getByRole("checkbox", { name: "billing" })).not.toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "Every case" }));
    expect(screen.getByRole("checkbox", { name: "returns" })).not.toBeChecked();
  });
});

it("renders the conversation and all expectations without joining their text", () => {
  const content = {
    input: "Where is my order?",
    history: [
      { role: "user" as const, content: "Earlier question" },
      { role: "assistant" as const, content: "Earlier answer" },
    ],
    reference_answer: "It arrives tomorrow.",
    counter_example: "I do not know.",
    expected_tool_calls: [
      { tool: "lookup_order", args: { id: "42" } },
      { tool: "clock", args: {} },
    ],
    order_mode: "in_order" as const,
    checks: [{ type: "contains" as const, value: "tomorrow" }],
    tags: ["shipping"],
    note: "Confirm the delivery date.",
  };
  const { rerender } = render(<CaseView content={content} />);
  for (const text of [
    "Earlier question",
    "Earlier answer",
    "Where is my order?",
    "It arrives tomorrow.",
    "I do not know.",
    "shipping",
    "Confirm the delivery date.",
  ])
    expect(screen.getByText(text)).toBeInTheDocument();
  expect(screen.getByText(/lookup_order/)).toHaveTextContent('"id":"42"');
  rerender(
    <CaseView
      content={{
        ...content,
        history: [],
        reference_answer: null,
        counter_example: null,
        expected_tool_calls: [],
        checks: [],
        tags: [],
        note: null,
      }}
    />,
  );
  expect(screen.queryByText("Earlier answer")).not.toBeInTheDocument();
});
