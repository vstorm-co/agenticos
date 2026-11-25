import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RoomMessageReactionSummary } from "@/types/room-message-reaction";
import messages from "@/../messages/en.json";
import { RoomMessageReactions } from "./room-message-reactions";

const hooks = vi.hoisted(() => ({
  reactions: [] as RoomMessageReactionSummary[],
  add: vi.fn(),
  remove: vi.fn(),
  retry: vi.fn(),
  isPending: false,
  hasError: false,
}));

vi.mock("@/hooks/use-room-message-reactions", () => ({
  useRoomMessageReactions: () => hooks,
}));

function draw(canReact = true, align: "start" | "end" = "start") {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RoomMessageReactions
        conversationId="room-1"
        messageId="message-1"
        initialReactions={hooks.reactions}
        canReact={canReact}
        align={align}
      />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  hooks.reactions = [
    { emoji: "👍", count: 3, reacted_by_me: true },
    { emoji: "🎉", count: 1, reacted_by_me: false },
  ];
  hooks.add.mockReset().mockResolvedValue(true);
  hooks.remove.mockReset().mockResolvedValue(true);
  hooks.retry.mockReset().mockResolvedValue(true);
  hooks.isPending = false;
  hooks.hasError = false;
});

describe("RoomMessageReactions", () => {
  it("shows aggregate counts and toggles the caller’s existing reaction", async () => {
    const user = userEvent.setup();
    draw();

    const selected = screen.getByRole("button", { name: "👍 3" });
    expect(selected).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "🎉 1" })).toHaveAttribute("aria-pressed", "false");
    await user.click(selected);

    expect(hooks.remove).toHaveBeenCalledWith("👍");
    expect(hooks.add).not.toHaveBeenCalled();
  });

  it("shows reactions without a mutation control to a reader who cannot post", () => {
    draw(false);

    expect(screen.getByLabelText("👍 3")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "👍 3" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add reaction" })).not.toBeInTheDocument();
  });

  it("offers common emoji and accepts a custom emoji", async () => {
    const user = userEvent.setup();
    draw();

    await user.click(screen.getByRole("button", { name: "Add reaction" }));
    await user.click(screen.getByRole("button", { name: "🚀" }));
    expect(hooks.add).toHaveBeenCalledWith("🚀");

    await user.click(screen.getByRole("button", { name: "Add reaction" }));
    await user.type(screen.getByRole("textbox", { name: "Type or paste an emoji" }), "👩🏽‍💻");
    await user.click(screen.getByRole("button", { name: /^Add$/ }));
    expect(hooks.add).toHaveBeenCalledWith("👩🏽‍💻");
  });

  it("adds a reaction the caller has not used yet", async () => {
    const user = userEvent.setup();
    draw();

    await user.click(screen.getByRole("button", { name: "🎉 1" }));

    expect(hooks.add).toHaveBeenCalledWith("🎉");
    expect(hooks.remove).not.toHaveBeenCalled();
  });

  it("right-aligns the reactions for the caller's own messages", () => {
    const { container } = draw(true, "end");

    expect(container.firstElementChild).toHaveClass("justify-end");
  });

  it("keeps the picker and typed emoji when saving fails, and ignores a blank custom emoji", async () => {
    hooks.add.mockResolvedValue(false);
    const user = userEvent.setup();
    draw(true, "end");

    await user.click(screen.getByRole("button", { name: "Add reaction" }));
    await user.click(screen.getByRole("button", { name: "🚀" }));
    expect(screen.getByRole("textbox", { name: "Type or paste an emoji" })).toBeVisible();

    const input = screen.getByRole("textbox", { name: "Type or paste an emoji" });
    await user.type(input, "   ");
    fireEvent.submit(input.closest("form")!);
    expect(hooks.add).toHaveBeenCalledTimes(1);

    await user.clear(input);
    await user.type(input, "🔥{Enter}");
    expect(hooks.add).toHaveBeenLastCalledWith("🔥");
    expect(input).toHaveValue("🔥");
  });

  it("lets the caller retry after a failed reaction", async () => {
    hooks.hasError = true;
    const user = userEvent.setup();
    draw();

    expect(screen.getByRole("alert")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(hooks.retry).toHaveBeenCalledOnce();
  });
});
