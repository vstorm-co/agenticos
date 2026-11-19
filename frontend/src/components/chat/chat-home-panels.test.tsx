import { fireEvent, render, screen, within } from "@testing-library/react";
import { createPortal } from "react-dom";
import { useState } from "react";
import Link from "next/link";
import { expect, it, vi } from "vitest";

import { ChatHomePanels } from "./chat-home-panels";

vi.mock("./chat-home-inbox", () => ({
  useChatHomeInbox: () => ({ suggested: { suggestions: [{ id: "a" }] }, pending: { count: 1 } }),
  ChatHomeInbox: ({ expanded }: { expanded: boolean }) => (
    <Link href="/inbox#suggestion-a">{expanded ? "Expanded topics" : "Cached topic"}</Link>
  ),
}));

it("shows Inbox and its count alongside working prompt actions", () => {
  const pick = vi.fn();
  function Home() {
    const [slot, setSlot] = useState<HTMLDivElement | null>(null);
    return (
      <>
        <ChatHomePanels suggestionsRef={setSlot} />
        {slot && createPortal(<button onClick={pick}>Try a prompt</button>, slot)}
      </>
    );
  }
  render(<Home />);

  expect(screen.getByRole("heading", { name: "Inbox, 2 waiting" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Cached topic" })).toBeVisible();
  const prompts = screen.getByRole("region", { name: "Suggested prompts" });
  fireEvent.click(within(prompts).getByRole("button", { name: "Try a prompt" }));
  expect(pick).toHaveBeenCalledOnce();
});

it("gives Inbox the entire preview when the agent hides prompts", () => {
  render(<ChatHomePanels suggestionsRef={vi.fn()} showPrompts={false} />);
  expect(screen.queryByRole("region", { name: "Suggested prompts" })).toBeNull();
  expect(screen.getByRole("link", { name: "Expanded topics" })).toBeVisible();
});
