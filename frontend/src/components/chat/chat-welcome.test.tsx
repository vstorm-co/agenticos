import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Ban, Sparkles } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { ChatWelcome, WelcomeIcon } from "./chat-welcome";

describe("ChatWelcome", () => {
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
