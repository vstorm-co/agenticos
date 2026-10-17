import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReplyQuote, ReplyingTo, replyExcerpt } from "./reply-quote";
import { useAuthStore } from "@/stores";

const anna = { user_id: "u-2", name: "Anna", has_avatar: false, avatar_color: null };

beforeEach(() => {
  useAuthStore.setState({ user: { id: "u-1", email: "k@example.com" } as never });
});

describe("ReplyQuote", () => {
  it("says whom the turn answers - a teammate, the reader, or an agent by name", () => {
    const { rerender } = render(
      <ReplyQuote reply={{ messageId: "m", role: "user", excerpt: "x", sender: anna }} />,
    );
    expect(screen.getByText("In reply to Anna")).toBeInTheDocument();

    rerender(<ReplyQuote reply={{ messageId: "m", role: "user", excerpt: "x" }} />);
    expect(screen.getByText("In reply to you")).toBeInTheDocument();

    rerender(
      <ReplyQuote
        reply={{ messageId: "m", role: "assistant", excerpt: "x", agentId: "a-1" }}
        agents={[{ id: "a-1", name: "Analyst" }]}
        align="start"
      />,
    );
    expect(screen.getByText("In reply to Analyst")).toBeInTheDocument();

    rerender(<ReplyQuote reply={{ messageId: "m", role: "assistant", excerpt: "x" }} />);
    expect(screen.getByText("In reply to The agent")).toBeInTheDocument();
  });

  it("goes to the message it quotes, and lights it for a moment", async () => {
    const target = document.createElement("div");
    target.dataset.messageId = "m-7";
    target.scrollIntoView = vi.fn();
    target.animate = vi.fn();
    document.body.append(target);

    render(<ReplyQuote reply={{ messageId: "m-7", role: "assistant", excerpt: "Plan: A" }} />);
    await userEvent.click(screen.getByRole("button", { name: "Plan: A" }));

    expect(target.scrollIntoView).toHaveBeenCalled();
    expect(target.animate).toHaveBeenCalled();
    target.remove();
  });

  it("does nothing for a quoted message no longer on screen", async () => {
    render(<ReplyQuote reply={{ messageId: "gone", role: "assistant", excerpt: "old" }} />);
    await userEvent.click(screen.getByRole("button", { name: "old" }));
  });

  it("folds a message into one short line", () => {
    expect(replyExcerpt("a\n\n  b")).toBe("a b");
    expect(replyExcerpt("x".repeat(300))).toBe(`${"x".repeat(280)}…`);
  });
});

describe("ReplyingTo", () => {
  it("names whom the reply being written answers, and lets it be dropped", async () => {
    const cancel = vi.fn();
    const { rerender } = render(
      <ReplyingTo
        reply={{ messageId: "m", role: "assistant", excerpt: "Plan", agentName: "Analyst" }}
        onCancel={cancel}
      />,
    );
    expect(screen.getByText("Analyst")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Don't reply" }));
    expect(cancel).toHaveBeenCalled();

    rerender(
      <ReplyingTo reply={{ messageId: "m", role: "user", excerpt: "x" }} onCancel={cancel} />,
    );
    expect(screen.getByText("Replying to yourself")).toBeInTheDocument();
  });
});
