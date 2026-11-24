import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AssistantWelcome } from "./assistant-welcome";

function renderWelcome(page: { path: string; title: string } | null) {
  const onPick = vi.fn();
  render(
    <AssistantWelcome greeting="Hello" name="Architect" mark={null} page={page} onPick={onPick} />,
  );
  return onPick;
}

describe("the assistant's look-around suggestion", () => {
  it("names the current page by its title and path", async () => {
    const onPick = renderWelcome({ path: "/agents", title: "Agents" });

    await userEvent.click(screen.getByRole("button", { name: /What am I looking at\?/ }));

    expect(onPick).toHaveBeenCalledWith(
      "I'm on the page \"Agents\" (/agents). Explain what I'm looking at and what I can do here, in plain language.",
    );
  });

  it("asks about the platform when no page is shared", async () => {
    const onPick = renderWelcome(null);

    await userEvent.click(screen.getByRole("button", { name: /What am I looking at\?/ }));

    expect(onPick).toHaveBeenCalledWith(
      "Explain what this platform can do for me, in plain language.",
    );
  });
});
