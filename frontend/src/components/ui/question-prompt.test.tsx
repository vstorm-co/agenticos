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
    expect(screen.getByText("Who will use it?").closest("[data-direction]")).toHaveAttribute(
      "data-direction",
      "forward",
    );

    await userEvent.click(screen.getByRole("button", { name: "Previous question" }));

    expect(screen.getByPlaceholderText("Type your answer…")).toHaveValue("Soon");
    expect(
      screen.getByPlaceholderText("Type your answer…").closest("[data-direction]"),
    ).toHaveAttribute("data-direction", "backward");
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

  it("lets a multi-select come back from its own answer to continue with the picks", async () => {
    const onComplete = vi.fn();
    render(<QuestionPrompt questions={[CHANNELS]} onComplete={onComplete} />);

    await userEvent.click(screen.getByRole("button", { name: /Slack/ }));
    await userEvent.click(screen.getByRole("button", { name: /Something else/ }));
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back to the options" }));
    await userEvent.click(screen.getByRole("button", { name: /Something else/ }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(onComplete).toHaveBeenCalledWith([{ answer: "", selected: ["Slack"], skipped: false }]);
  });

  it("disables everything while the connection is down", () => {
    render(<QuestionPrompt questions={[AUDIENCE, FREE]} disabled onComplete={vi.fn()} />);

    expect(screen.getByRole("button", { name: /Everyone/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Dismiss questions" })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("group"), { key: "1" });
  });
  it("does not submit the Enter used to finish IME composition", () => {
    const onComplete = vi.fn();
    render(<QuestionPrompt questions={[FREE]} onComplete={onComplete} autoFocus={false} />);
    const input = screen.getByPlaceholderText("Type your answer…");
    fireEvent.change(input, { target: { value: "日本語" } });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    expect(onComplete).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onComplete).toHaveBeenCalledWith([{ answer: "日本語", skipped: false }]);
  });
  it("keeps keyboard navigation in the review without scrolling the transcript", () => {
    render(
      <QuestionPrompt questions={[AUDIENCE, AUDIENCE]} onComplete={vi.fn()} autoFocus={false} />,
    );
    fireEvent.keyDown(screen.getByRole("group"), { key: "1" });
    expect(screen.getByRole("group")).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("group"), { key: "1" });
    expect(
      screen.getByRole("button", { name: "Send answers" }).parentElement?.parentElement,
    ).toHaveFocus();
  });
  it("does not restart inline-question focus when tabbing between options", async () => {
    render(<QuestionPrompt questions={[AUDIENCE]} onComplete={vi.fn()} autoFocus={false} />);
    const first = screen.getByRole("button", { name: /Everyone/ });
    first.focus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: /My team/ })).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(first).toHaveFocus();
  });
  it("lets Shift+Tab leave a custom input without autofocus pulling it back", async () => {
    render(<QuestionPrompt questions={[FREE]} onComplete={vi.fn()} autoFocus={false} />);
    screen.getByPlaceholderText("Type your answer…").focus();
    await userEvent.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Dismiss questions" })).toHaveFocus();
  });
});

it("keeps native editor whitespace and permits an explicit empty replacement", async () => {
  const onComplete = vi.fn();
  render(
    <QuestionPrompt
      questions={[
        {
          question: "Edit",
          requestId: "native-one",
          multiline: true,
          initialValue: "  original\n",
          allowEmpty: true,
        },
      ]}
      onComplete={onComplete}
    />,
  );
  const editor = screen.getByRole("textbox");
  expect(editor.tagName).toBe("TEXTAREA");
  expect(editor).toHaveValue("  original\n");
  await userEvent.clear(editor);
  await userEvent.type(editor, "  indented{enter}next");
  expect(onComplete).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Use this" }));
  expect(onComplete).toHaveBeenLastCalledWith([{ answer: "  indented\nnext", skipped: false }]);
  await userEvent.clear(editor);
  await userEvent.click(screen.getByRole("button", { name: "Use this" }));
  expect(onComplete).toHaveBeenLastCalledWith([{ answer: "", skipped: false }]);
});

it("enforces a native selection range and sends the offered identities", async () => {
  const onComplete = vi.fn();
  render(
    <QuestionPrompt
      questions={[
        {
          question: "Pick two",
          multiSelect: true,
          minSelections: 2,
          maxSelections: 2,
          allowCustom: false,
          options: [{ label: "A" }, { label: "B" }, { label: "C" }],
        },
      ]}
      onComplete={onComplete}
    />,
  );
  const submit = screen.getByRole("button", { name: "Continue" });
  expect(submit).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: /^1\s*A$/ }));
  expect(submit).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: /^2\s*B$/ }));
  expect(screen.getByRole("button", { name: /^3\s*C$/ })).toBeDisabled();
  await userEvent.click(submit);
  expect(onComplete).toHaveBeenCalledWith([{ answer: "", selected: ["A", "B"], skipped: false }]);
});

it("resets editor and carousel state for a new native request identity", async () => {
  const onComplete = vi.fn();
  const { rerender } = render(
    <QuestionPrompt
      questions={[
        { question: "Edit", requestId: "one", multiline: true, initialValue: "original" },
      ]}
      onComplete={onComplete}
    />,
  );
  await userEvent.clear(screen.getByRole("textbox"));
  await userEvent.type(screen.getByRole("textbox"), "Stale answer");
  rerender(
    <QuestionPrompt
      questions={[
        { question: "Edit", requestId: "two", multiline: true, initialValue: "New request" },
      ]}
      onComplete={onComplete}
    />,
  );
  expect(screen.getByRole("textbox")).toHaveValue("New request");
});

it("localizes synthetic native controls without changing the protocol label", async () => {
  const onComplete = vi.fn();
  render(
    <QuestionPrompt
      questions={[
        {
          question: "Review plan",
          allowCustom: false,
          options: [
            { label: "approved-wire-value", labelKey: "runtimeApprovePlan" },
            { label: "rejected-wire-value", labelKey: "runtimeRejectPlan" },
          ],
        },
      ]}
      onComplete={onComplete}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: /Approve plan/ }));
  expect(onComplete).toHaveBeenCalledWith([
    { answer: "", selected: ["approved-wire-value"], skipped: false },
  ]);
});

it("focuses pointer choices without the browser scrolling them between press and release", async () => {
  const focus = vi.spyOn(HTMLElement.prototype, "focus");
  const onComplete = vi.fn();
  render(
    <QuestionPrompt
      questions={[
        { question: "Format?", options: [{ label: "List" }], allowCustom: false },
        { question: "Length?", options: [{ label: "Short" }], allowCustom: false },
      ]}
      onComplete={onComplete}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: /1\s*List/ }));
  expect(focus).toHaveBeenCalledWith({ preventScroll: true });
  await userEvent.click(screen.getByRole("button", { name: /1\s*Short/ }));
  await userEvent.click(screen.getByRole("button", { name: "Send answers" }));
  expect(onComplete).toHaveBeenCalledWith([
    { answer: "", selected: ["List"], skipped: false },
    { answer: "", selected: ["Short"], skipped: false },
  ]);
  focus.mockRestore();
});
