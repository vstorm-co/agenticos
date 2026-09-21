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
