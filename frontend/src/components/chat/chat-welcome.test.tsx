import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Ban, Sparkles } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { ChatWelcome, WelcomeIcon } from "./chat-welcome";

describe("ChatWelcome", () => {
  it("puts suggestions into the composer slot without first drawing them in the greeting", () => {
    const target = document.createElement("div");
    document.body.append(target);
    const props = {
      mark: <span />,
      title: "Welcome",
      lead: "Ready",
      quiet: true,
      suggestions: [{ key: "a", icon: Ban, title: "A starter", prompt: "Start" }],
      onPick: vi.fn(),
    };
    const view = render(<ChatWelcome {...props} suggestionsSlot={null} />);
    expect(screen.queryByText("A starter")).toBeNull();
    view.rerender(<ChatWelcome {...props} suggestionsSlot={target} />);
    expect(target).toHaveTextContent("A starter");
    expect(view.container).not.toHaveTextContent("A starter");
    view.unmount();
    expect(target).toBeEmptyDOMElement();
    target.remove();
  });

  it("sends a card's prompt and says it under the title when nothing else is written", async () => {
    const onPick = vi.fn();
    render(
      <ChatWelcome
        mark={<WelcomeIcon icon={Sparkles} />}
        title="What can I help with?"
        lead="Ask anything."
        suggestions={[{ key: "a", icon: Ban, title: "Refuse", prompt: "Say no politely" }]}
        onPick={onPick}
        footer={<span>Press / for commands</span>}
      />,
    );

    expect(screen.getByText("Say no politely")).toBeInTheDocument();
    expect(screen.getByText("Press / for commands")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Refuse/ }));
    expect(onPick).toHaveBeenCalledWith("Say no politely");
  });

  it("shows a pinned card's own description and takes it off without sending it", async () => {
    const onPick = vi.fn();
    const onRemove = vi.fn();
    render(
      <ChatWelcome
        compact
        mark={<span />}
        title="Test Amigo"
        lead="Talks to the draft."
        suggestions={[
          {
            key: "p",
            icon: Ban,
            title: "Who are you?",
            prompt: "Who are you?",
            description: "Pinned - ask again after each change",
            onRemove,
          },
        ]}
        onPick={onPick}
      />,
    );

    expect(screen.getByText("Pinned - ask again after each change")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Unpin/ }));
    expect(onRemove).toHaveBeenCalledOnce();
    expect(onPick).not.toHaveBeenCalled();
  });
});

it("keeps the quiet starter's icon, title and description on view", () => {
  const { container } = render(
    <ChatWelcome
      quiet
      mark={<span />}
      title="Welcome"
      lead="Ready"
      suggestions={[
        {
          key: "draft",
          icon: Ban,
          title: "A starter",
          description: "A short description",
          prompt: "The full prompt",
        },
      ]}
      onPick={vi.fn()}
    />,
  );
  expect(screen.getByText("A short description")).not.toHaveClass("sr-only");
  expect(container.querySelector(".lucide-ban")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /A starter\s*A short description/ })).toBeVisible();
});

it("retains greeting and starter slots when personal preferences hide them", () => {
  render(
    <ChatWelcome
      mark={<span />}
      title="Welcome back"
      lead="Discover what you can do"
      suggestions={[{ key: "first", icon: Ban, title: "First suggestion", prompt: "Start" }]}
      onPick={vi.fn()}
      quiet
      showGreeting={false}
      showLead={false}
      showSuggestions={false}
    />,
  );
  expect(screen.getByText("Welcome back")).toHaveClass("invisible");
  expect(screen.getByText("Welcome back")).toHaveAttribute("aria-hidden", "true");
  expect(screen.getByText("Discover what you can do")).toHaveClass("invisible");
  const hints = screen.getByText("First suggestion").closest("[data-chat-welcome-hints]");
  expect(hints).toHaveAttribute("inert");
  expect(hints).toHaveAttribute("data-suggestions-hidden", "true");
});

it("keeps the docked editor focused until a starter click prefills it", async () => {
  const target = document.createElement("div");
  document.body.append(target);
  const onPick = vi.fn();
  const view = render(
    <>
      <div role="textbox" aria-label="Message" contentEditable="true" />
      <ChatWelcome
        quiet
        mark={<span />}
        title="Welcome"
        lead="Ready"
        suggestionsSlot={target}
        suggestions={[{ key: "a", icon: Ban, title: "A starter", prompt: "Draft a summary" }]}
        onPick={onPick}
      />
    </>,
  );
  const editor = screen.getByRole("textbox", { name: "Message" });
  const starter = screen.getByRole("button", { name: /A starter/ });
  editor.focus();
  const press = new MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 });
  fireEvent(starter, press);
  expect(press.defaultPrevented).toBe(true);
  expect(editor).toHaveFocus();
  expect(onPick).not.toHaveBeenCalled();
  fireEvent.click(starter);
  expect(editor).toHaveFocus();
  expect(onPick).toHaveBeenCalledExactlyOnceWith("Draft a summary");

  // Mouse focus protection must not prevent native keyboard activation.
  starter.focus();
  await userEvent.keyboard("{Enter}");
  expect(onPick).toHaveBeenCalledTimes(2);
  expect(starter).toHaveFocus();
  view.unmount();
  target.remove();
});
