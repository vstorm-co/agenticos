import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { QuestionPrompt } from "./question-prompt";
import type { QuestionPromptItem } from "./question-slide";

const AUDIENCE: QuestionPromptItem = {
  header: "Audience",
  question: "Who will use it?",
  options: [{ label: "Everyone", description: "The whole organization" }, { label: "My team" }],
};
const CHANNELS: QuestionPromptItem = {
  header: "Channels",
  question: "Where should it answer?",
  options: [{ label: "Slack" }, { label: "Website" }, { label: "Email" }],
  multiSelect: true,
};
const FREE: QuestionPromptItem = { question: "Anything else?" };

describe("QuestionPrompt", () => {
  it("draws nothing for no questions", () => {
    const { container } = render(<QuestionPrompt questions={[]} onComplete={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("answers a single question the moment an option is picked", async () => {
    const onComplete = vi.fn();
    render(<QuestionPrompt questions={[AUDIENCE]} onComplete={onComplete} />);

    expect(screen.getByText("Audience")).toBeInTheDocument();
    expect(screen.getByText("The whole organization")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /My team/ }));

    expect(onComplete).toHaveBeenCalledWith([
      { answer: "", selected: ["My team"], skipped: false },
    ]);
  });

  it("steps through several questions, then sends them from a summary", async () => {
    const onComplete = vi.fn();
    render(<QuestionPrompt questions={[AUDIENCE, CHANNELS, FREE]} onComplete={onComplete} />);

    expect(screen.getByText("Question 1 of 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Everyone/ }));

    expect(screen.getByText("Pick as many as apply.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Slack/ }));
    await userEvent.click(screen.getByRole("button", { name: /Email/ }));
    await userEvent.click(screen.getByRole("button", { name: /Email/ }));
    await userEvent.click(screen.getByRole("button", { name: /Website/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    // A question without options opens straight on the free answer.
    await userEvent.type(screen.getByPlaceholderText("Type your answer…"), "Be brief{Enter}");

    expect(screen.getByText("Your answers")).toBeInTheDocument();
    expect(screen.getByText("Slack, Website")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send answers" }));

    expect(onComplete).toHaveBeenCalledWith([
      { answer: "", selected: ["Everyone"], skipped: false },
      { answer: "", selected: ["Slack", "Website"], skipped: false },
      { answer: "Be brief", skipped: false },
    ]);
  });

  it("goes back to change an answer, keeping what was typed", async () => {
    render(<QuestionPrompt questions={[FREE, AUDIENCE]} onComplete={vi.fn()} />);

    await userEvent.type(screen.getByPlaceholderText("Type your answer…"), "Soon");
    await userEvent.click(screen.getByRole("button", { name: "Use this" }));
    expect(screen.getByText("Question 2 of 2")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Previous question" }));

    expect(screen.getByPlaceholderText("Type your answer…")).toHaveValue("Soon");
    await userEvent.click(screen.getByRole("button", { name: "Go to question 2" }));
    expect(screen.getByText("Who will use it?")).toBeInTheDocument();
  });

  it("skips one question, and × skips whatever is left", async () => {
    const onComplete = vi.fn();
    render(<QuestionPrompt questions={[AUDIENCE, CHANNELS]} onComplete={onComplete} />);

    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(screen.getByText("Question 2 of 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss questions" }));

    expect(onComplete).toHaveBeenCalledWith([
      { answer: "", skipped: true },
      { answer: "", skipped: true },
    ]);
  });

  it("says Skipped in the summary for a question passed over", async () => {
    render(<QuestionPrompt questions={[AUDIENCE, FREE]} onComplete={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));

    expect(screen.getAllByText("Skipped")).toHaveLength(2);
  });

  it("is driven from the keyboard: digits pick, arrows move, Enter chooses", () => {
    const onComplete = vi.fn();
    render(
      <QuestionPrompt
        questions={[{ ...AUDIENCE, options: [...AUDIENCE.options!, { label: "Only me" }] }]}
        onComplete={onComplete}
      />,
    );
    const group = screen.getByRole("group");

    fireEvent.keyDown(group, { key: "9" });
    fireEvent.keyDown(group, { key: "x" });
    fireEvent.keyDown(group, { key: "ArrowDown" });
    fireEvent.keyDown(group, { key: "ArrowDown" });
    fireEvent.keyDown(group, { key: "ArrowDown" });
    fireEvent.keyDown(group, { key: "ArrowUp" });
    fireEvent.keyDown(group, { key: "Enter" });
    expect(onComplete).toHaveBeenLastCalledWith([
      { answer: "", selected: ["My team"], skipped: false },
    ]);
  });

  it("picks an option by its digit", () => {
    const onComplete = vi.fn();
    render(<QuestionPrompt questions={[AUDIENCE]} onComplete={onComplete} />);

    fireEvent.keyDown(screen.getByRole("group"), { key: "1" });

    expect(onComplete).toHaveBeenCalledWith([
      { answer: "", selected: ["Everyone"], skipped: false },
    ]);
  });

  it("ignores keys while typing an answer, a blank answer, and closed free text", async () => {
    const onComplete = vi.fn();
    render(
      <QuestionPrompt
        questions={[{ ...AUDIENCE, allowCustom: false }, AUDIENCE]}
        onComplete={onComplete}
      />,
    );

    expect(screen.queryByText("Something else")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Everyone/ }));
    await userEvent.click(screen.getByRole("button", { name: /Something else/ }));
    fireEvent.keyDown(screen.getByRole("group"), { key: "1" });
    await userEvent.type(screen.getByPlaceholderText("Type your answer…"), "   {Enter}");

    expect(screen.getByRole("button", { name: "Use this" })).toBeDisabled();
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("disables everything while the connection is down", () => {
    render(<QuestionPrompt questions={[AUDIENCE, FREE]} disabled onComplete={vi.fn()} />);

    expect(screen.getByRole("button", { name: /Everyone/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Dismiss questions" })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("group"), { key: "1" });
  });
});
