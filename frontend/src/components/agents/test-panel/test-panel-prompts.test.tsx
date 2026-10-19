import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TestPanelPrompts } from "./test-panel-prompts";

describe("the prompts strip shown while comparing", () => {
  it("asks a pinned question in both panes and unpins one", async () => {
    const onAsk = vi.fn();
    const onPinnedChange = vi.fn();
    render(
      <TestPanelPrompts
        pinned={["Who are you?", "What can you do?"]}
        comparing
        onAsk={onAsk}
        onPinnedChange={onPinnedChange}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Who are you?" }));
    expect(onAsk).toHaveBeenCalledWith("Who are you?");

    await userEvent.click(screen.getByRole("button", { name: /Unpin.*Who are you\?/ }));
    expect(onPinnedChange).toHaveBeenCalledWith(["What can you do?"]);
  });
});
