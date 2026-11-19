import { act, fireEvent, render, screen } from "@testing-library/react";
import { createPortal } from "react-dom";
import { useState } from "react";
import Link from "next/link";
import { afterEach, expect, it, vi } from "vitest";

import { ChatHomeCarousel } from "./chat-home-carousel";

vi.mock("./chat-home-inbox", () => ({
  ChatHomeInbox: () => <Link href="/inbox">Cached topic</Link>,
}));
vi.mock("@/lib/motion", () => ({ glideOrJump: () => "auto" }));
afterEach(() => vi.useRealTimers());

function setup() {
  function Home() {
    const [slot, setSlot] = useState<HTMLDivElement | null>(null);
    return (
      <>
        <ChatHomeCarousel suggestionsRef={setSlot} />
        {slot && createPortal(<button>Try a prompt</button>, slot)}
      </>
    );
  }
  render(<Home />);
  const track = screen.getByRole("group", { name: "Pages" });
  Object.defineProperty(track, "clientWidth", { value: 400 });
  const second = screen.getByRole("group", { name: "Suggested prompts, 2 of 2" });
  Object.defineProperty(second, "offsetLeft", { value: 400 });
  const scroll = vi.fn();
  track.scrollTo = scroll;
  return { track, scroll };
}

it("starts on Inbox and keeps cached content and prompt actions mounted", () => {
  const { track, scroll } = setup();
  expect(screen.getByRole("button", { name: "Inbox" })).toHaveAttribute("aria-current", "true");
  expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
  expect(screen.getByRole("status")).toBeEmptyDOMElement();
  const topic = screen.getByRole("link", { name: "Cached topic" });
  screen.getByRole("button", { name: "Next page" }).focus();
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  expect(scroll).toHaveBeenCalledWith({ left: 400, behavior: "auto" });
  expect(screen.getByRole("button", { name: "Suggested prompts" })).toHaveFocus();
  expect(screen.getByRole("button", { name: "Suggested prompts" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  expect(screen.getByRole("button", { name: "Try a prompt" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Cached topic" })).toBe(topic);
  act(() => {
    track.scrollLeft = 400;
    fireEvent.scroll(track);
    fireEvent(track, new Event("scrollend"));
  });
});

it("synchronizes markers and announcements after a native swipe", () => {
  vi.useFakeTimers();
  const { track } = setup();
  act(() => {
    track.scrollLeft = 400;
    fireEvent.scroll(track);
    fireEvent(track, new Event("scrollend"));
    vi.advanceTimersByTime(150);
  });
  expect(screen.getByRole("button", { name: "Suggested prompts" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  expect(screen.getByRole("status")).toHaveTextContent("Page 2 of 2");
});

it("does not leave a pending target when the current marker is clicked", () => {
  vi.useFakeTimers();
  const { track, scroll } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Inbox" }));
  expect(scroll).not.toHaveBeenCalled();
  act(() => {
    track.scrollLeft = 400;
    fireEvent.scroll(track);
    fireEvent(track, new Event("scrollend"));
    vi.advanceTimersByTime(150);
  });
  expect(screen.getByRole("status")).toHaveTextContent("Page 2 of 2");
});

it("announces settled scrolling when scrollend is unavailable", () => {
  vi.useFakeTimers();
  let owner: object | null = HTMLElement.prototype;
  while (owner && !Object.getOwnPropertyDescriptor(owner, "onscrollend")) {
    const parent: unknown = Object.getPrototypeOf(owner);
    owner = typeof parent === "object" ? parent : null;
  }
  const descriptor = owner && Object.getOwnPropertyDescriptor(owner, "onscrollend");
  if (owner) Reflect.deleteProperty(owner, "onscrollend");
  try {
    const { track } = setup();
    act(() => {
      track.scrollLeft = 400;
      fireEvent.scroll(track);
      vi.advanceTimersByTime(119);
    });
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole("status")).toHaveTextContent("Page 2 of 2");
  } finally {
    if (owner && descriptor) Object.defineProperty(owner, "onscrollend", descriptor);
  }
});
