import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { ToolCall } from "@/types";
import { QuestionTurnCard } from "./question-turn-card";
import type { QuestionInteraction } from "./question-interaction";
vi.mock("./tool-call-card", () => ({ ToolCallCard: () => <span>Invocation diagnostics</span> }));
const call: ToolCall = {
  id: "q",
  name: "ask_user_question",
  status: "awaiting_answer",
  args: {
    questions: [{ header: "Format", question: "Which format?", options: [{ label: "List" }] }],
  },
};
const active = (onAnswer = vi.fn()): QuestionInteraction => ({
  id: "q",
  messageId: "m",
  toolCallIds: ["q"],
  questions: [
    {
      header: "Format",
      question: "Which format?",
      options: [{ label: "List" }],
      allowCustom: true,
    },
  ],
  submitting: false,
  disabled: false,
  onAnswer,
});
it("keeps one card through waiting, submission and acknowledged replay", async () => {
  const interaction = active();
  const view = render(<QuestionTurnCard calls={[call]} interaction={interaction} />);
  const card = view.container.querySelector("[data-chat-question]");
  await userEvent.click(screen.getByRole("button", { name: /1\s*List/ }));
  expect(interaction.onAnswer).toHaveBeenCalledOnce();
  view.rerender(
    <QuestionTurnCard calls={[call]} interaction={{ ...interaction, submitting: true }} />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("Sending your answers…");
  expect(screen.getByRole("button", { name: /1\s*List/ })).toBeDisabled();
  view.rerender(
    <QuestionTurnCard calls={[{ ...call, status: "completed", result: '{"Format":["List"]}' }]} />,
  );
  expect(view.container.querySelector("[data-chat-question]")).toBe(card);
  expect(screen.getByText("Questions and answers").closest("summary")).toHaveTextContent("List");
  expect(screen.queryByRole("button", { name: /1\s*List/ })).toBeNull();
});
it("does not move focus from the reader when an inline question arrives", () => {
  const focus = document.createElement("button");
  document.body.append(focus);
  focus.focus();
  render(<QuestionTurnCard calls={[call]} interaction={active()} />);
  expect(focus).toHaveFocus();
  focus.remove();
});
it("keeps offline choices disabled and old question payloads inspectable", () => {
  render(<QuestionTurnCard calls={[call]} interaction={{ ...active(), disabled: true }} />);
  expect(screen.getByRole("button", { name: /1\s*List/ })).toBeDisabled();
  expect(screen.getByText("Tool details")).toBeVisible();
});
