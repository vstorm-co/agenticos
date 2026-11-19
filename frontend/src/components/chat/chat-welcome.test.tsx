import { render, screen, within } from "@testing-library/react";
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

  it("shows one random prompt and keeps the pick stable when the composer changes", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const draw = vi.spyOn(Math, "random").mockReturnValue(0.6);
    const props = {
      mark: <span />,
      title: "Welcome",
      lead: "Ready",
      suggestions: [
        { key: "a", icon: Ban, title: "A starter", prompt: "Start here" },
        { key: "b", icon: Sparkles, title: "B starter", prompt: "Start there" },
      ],
      onPick: vi.fn(),
      suggestionsSlot: root,
      singleSuggestion: true,
    };
    try {
      const view = render(<ChatWelcome {...props} loading />);
      expect(within(root).queryByRole("button")).toBeNull();
      view.rerender(<ChatWelcome {...props} />);
      draw.mockReturnValue(0.1);
      view.rerender(<ChatWelcome {...props} lead="Standing by" />);
      expect(within(root).getAllByRole("button")).toHaveLength(1);
      await userEvent.click(within(root).getByRole("button", { name: "B starter" }));
      expect(props.onPick).toHaveBeenCalledWith("Start there");
      view.rerender(<ChatWelcome {...props} suggestions={[]} />);
      expect(within(root).queryByRole("button")).toBeNull();
      view.unmount();
    } finally {
      draw.mockRestore();
      root.remove();
    }
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
