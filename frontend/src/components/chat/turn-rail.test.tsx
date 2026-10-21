import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { TurnRail, previewOf, type RailEntry } from "./turn-rail";

/**
 * The map of a conversation down the edge of it. Every assertion here is about
 * the one promise it makes: what it draws is the transcript, and clicking a
 * tick goes to the message it stands for.
 */
function entries(count: number): RailEntry[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `m-${i}`,
    author: i % 2 === 0 ? "You" : "Support",
    preview: `message number ${i}`,
    isUser: i % 2 === 0,
    agentId: i % 2 === 0 ? undefined : "a-1",
    seed: i % 2 === 0 ? "u-1" : "a-1",
  }));
}

function rail(list: RailEntry[]) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TurnRail entries={list} />
    </NextIntlClientProvider>,
  );
}

describe("TurnRail", () => {
  it("draws one tick per message", () => {
    rail(entries(6));

    expect(screen.getAllByRole("button", { name: /Jump to the message/ })).toHaveLength(6);
  });

  it("stays away from a conversation too short to need a map", () => {
    // Three ticks tell a reader nothing they cannot see by scrolling a screen.
    const { container } = rail(entries(3));

    expect(container).toBeEmptyDOMElement();
  });

  it("names who spoke, so a tick is identifiable before it is clicked", async () => {
    rail(entries(6));

    await userEvent.hover(screen.getAllByRole("button", { name: /Jump to the message/ })[1]!);

    expect(screen.getByText("Support")).toBeVisible();
    expect(screen.getByText("message number 1")).toBeVisible();
  });

  it("scrolls the message it stands for into view", async () => {
    const anchor = document.createElement("div");
    anchor.setAttribute("data-message-id", "m-2");
    const scrollIntoView = vi.fn();
    anchor.scrollIntoView = scrollIntoView;
    document.body.append(anchor);
    rail(entries(6));

    await userEvent.click(screen.getAllByRole("button", { name: /Jump to the message/ })[2]!);

    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
    anchor.remove();
  });

  it("cannot step above the first message or below the last", async () => {
    rail(entries(6));

    // At the top there is nowhere previous to go, which the control says rather
    // than doing nothing when pressed.
    expect(screen.getByRole("button", { name: "Previous message" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next message" }));
    expect(screen.getByRole("button", { name: "Previous message" })).toBeEnabled();
  });
});

/**
 * The arrows, against a transcript laid out on a page. Six messages of uneven
 * length in a scroller whose top - and the chat column's - sits 100px down the
 * viewport. `offsets` is where each message starts in the scrolled content, so a
 * message's top on screen is `100 + offset - scrollTop`, and `scrollTo` moves
 * the content the way a browser would.
 */
function transcript(scrollTop: number) {
  const offsets = [0, 400, 1200, 1300, 2500, 2600];
  const lineTop = 100;
  let scrolled = scrollTop;
  const rect = (top: number) => ({ top }) as DOMRect;

  const scroller = document.createElement("div");
  scroller.style.overflowY = "auto";
  Object.defineProperty(scroller, "scrollTop", { get: () => scrolled });
  scroller.getBoundingClientRect = () => rect(lineTop);
  const scrollTo = vi.fn((options: ScrollToOptions) => {
    scrolled = options.top ?? scrolled;
  });
  scroller.scrollTo = scrollTo as unknown as typeof scroller.scrollTo;
  offsets.forEach((offset, i) => {
    const anchor = document.createElement("div");
    anchor.setAttribute("data-message-id", `m-${i}`);
    anchor.getBoundingClientRect = () => rect(lineTop + offset - scrolled);
    scroller.append(anchor);
  });

  // The rail's positioned parent: the chat column, whose top is the scroller's.
  const column = document.createElement("div");
  column.getBoundingClientRect = () => rect(lineTop);
  document.body.append(scroller, column);
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TurnRail entries={entries(offsets.length)} />
    </NextIntlClientProvider>,
    { container: column },
  );

  const lit = () =>
    screen
      .getAllByRole("button", { name: /Jump to the message/ })
      .findIndex((tick) => tick.getAttribute("aria-current") === "true");
  const cleanup = () => {
    scroller.remove();
    column.remove();
  };
  return { scrollTo, scrolled: () => scrolled, offsets, lit, cleanup };
}

describe("TurnRail arrows", () => {
  it("steps down from what is on screen, never up to a stale mark", async () => {
    // Half way into message 2, with the rail still marking message 0 - what a
    // jump or a scroll by hand leaves behind. Down is message 3, not message 1.
    const page = transcript(1250);

    await userEvent.click(screen.getByRole("button", { name: "Next message" }));

    expect(page.scrolled()).toBe(page.offsets[3]);
    expect(page.lit()).toBe(3);
    page.cleanup();
  });

  it("steps up to the last message starting above the top of the chat", async () => {
    const page = transcript(1250);
    // Mark a message further down than the reader is, as a stale mark would.
    await userEvent.click(screen.getAllByRole("button", { name: /Jump to the message/ })[4]!);

    await userEvent.click(screen.getByRole("button", { name: "Previous message" }));

    expect(page.scrolled()).toBe(page.offsets[2]);
    expect(page.lit()).toBe(2);
    page.cleanup();
  });

  it("walks one message per press, in either direction", async () => {
    const page = transcript(0);
    const next = screen.getByRole("button", { name: "Next message" });
    const previous = screen.getByRole("button", { name: "Previous message" });

    for (const expected of [1, 2, 3]) {
      await userEvent.click(next);
      expect(page.scrolled()).toBe(page.offsets[expected]);
      expect(page.lit()).toBe(expected);
    }
    for (const expected of [2, 1, 0]) {
      await userEvent.click(previous);
      expect(page.scrolled()).toBe(page.offsets[expected]);
      expect(page.lit()).toBe(expected);
    }
    page.cleanup();
  });

  it("scrolls the chat and nothing around it", async () => {
    const page = transcript(0);
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView");

    await userEvent.click(screen.getByRole("button", { name: "Next message" }));

    // `scrollIntoView` scrolls every scrollable ancestor; the arrows only move
    // the transcript's own scroller.
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(page.scrollTo).toHaveBeenCalledWith({ top: page.offsets[1], behavior: "smooth" });
    scrollIntoView.mockRestore();
    page.cleanup();
  });
});

/**
 * The card is a label for a message, not a second place to read it - so what it
 * shows is the message flattened, with the markdown taken out rather than
 * rendered.
 */
describe("previewOf", () => {
  it("takes the emphasis markers out rather than showing them", () => {
    expect(previewOf("I am running on **AgenticOS**, configured by a _spec_.")).toBe(
      "I am running on AgenticOS, configured by a spec.",
    );
  });

  it("keeps a link's words and drops its address", () => {
    expect(previewOf("See [the docs](https://example.test/a/b) for more.")).toBe(
      "See the docs for more.",
    );
  });

  it("drops a code block whole, because its first line says nothing", () => {
    expect(previewOf("Here it is:\n```py\nprint(1)\n```\nand that is all.")).toBe(
      "Here it is: and that is all.",
    );
  });

  it("flattens a list into the one line the card has room for", () => {
    expect(previewOf("What I can do:\n\n* search\n* answer\n* summarise")).toBe(
      "What I can do: search answer summarise",
    );
  });

  it("leaves ordinary prose alone", () => {
    expect(previewOf("  Warsaw was rebuilt after the war.  ")).toBe(
      "Warsaw was rebuilt after the war.",
    );
  });
});
