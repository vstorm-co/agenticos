import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReplyQuote, replyExcerpt } from "./reply-quote";
import { useAuthStore } from "@/stores";

const anna = { user_id: "u-2", name: "Anna", has_avatar: false, avatar_color: null };

beforeEach(() => {
  useAuthStore.setState({ user: { id: "u-1", email: "k@example.com" } as never });
});

describe("ReplyQuote", () => {
  it("names who wrote what a turn answers", () => {
    const { rerender } = render(
      <ReplyQuote reply={{ messageId: "m", role: "assistant", excerpt: "Plan: A, B" }} />,
    );
    expect(screen.getByText("The agent")).toBeInTheDocument();

    rerender(<ReplyQuote reply={{ messageId: "m", role: "user", excerpt: "x", sender: anna }} />);
    expect(screen.getByText("Anna")).toBeInTheDocument();

    rerender(
      <ReplyQuote
        reply={{ messageId: "m", role: "user", excerpt: "x", sender: { ...anna, user_id: "u-1" } }}
      />,
    );
    expect(screen.getByText("You")).toBeInTheDocument();
  });

  it("scrolls to the message it quotes", async () => {
    const target = document.createElement("div");
    target.dataset.messageId = "m-7";
    target.scrollIntoView = vi.fn();
    document.body.append(target);

    render(<ReplyQuote reply={{ messageId: "m-7", role: "assistant", excerpt: "x" }} />);
    await userEvent.click(screen.getByRole("button", { name: /The agent/ }));

    expect(target.scrollIntoView).toHaveBeenCalled();
    target.remove();
  });

  it("folds a message into one short line", () => {
    expect(replyExcerpt("a\n\n  b")).toBe("a b");
    expect(replyExcerpt("x".repeat(300))).toBe(`${"x".repeat(280)}…`);
  });
});
