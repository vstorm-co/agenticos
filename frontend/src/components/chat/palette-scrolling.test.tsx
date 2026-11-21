import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MentionPalette } from "./mention-palette";
import { SlashCommandPalette } from "./slash-command-palette";

// Opening a composer palette must not scroll the transcript or the document.
// Its keyboard highlight scrolls only the palette's own list.
afterEach(() => vi.restoreAllMocks());
it.each(["mentions", "commands"] as const)(
  "keeps %s navigation inside its own scrollport",
  (kind) => {
    let rowTop = 240;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.tagName === "UL"
        ? new DOMRect(0, 100, 300, 100)
        : new DOMRect(0, rowTop, 300, 30);
    });
    const ancestorScroll = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
    const draw = (index: number) =>
      kind === "mentions" ? (
        <MentionPalette
          items={[{ id: "a", name: "Example context", kind: "context" }]}
          selectedIndex={index}
          onSelectIndex={vi.fn()}
          onPick={vi.fn()}
          isLoading={false}
          failed={false}
        />
      ) : (
        <SlashCommandPalette
          commands={[
            {
              name: "clear",
              description: "Clear conversation",
              action: { kind: "client", run: vi.fn() },
            },
          ]}
          selectedIndex={index}
          onSelectIndex={vi.fn()}
          onPick={vi.fn()}
        />
      );
    const view = render(draw(0));
    const list = view.container.querySelector("ul")!;
    expect(list.scrollTop).toBe(70);
    rowTop = 60;
    view.rerender(draw(-1));
    view.rerender(draw(0));
    expect(list.scrollTop).toBe(30);
    rowTop = 120;
    view.rerender(draw(-1));
    view.rerender(draw(0));
    expect(list.scrollTop).toBe(30);
    expect(ancestorScroll).not.toHaveBeenCalled();
  },
);

it("offers an empty command search and keeps command picking in the composer", () => {
  const pick = vi.fn(),
    select = vi.fn();
  const view = render(
    <SlashCommandPalette commands={[]} selectedIndex={0} onSelectIndex={select} onPick={pick} />,
  );
  expect(screen.getByText(/No matching/)).toBeVisible();
  const command = {
    name: "clear",
    aliases: ["reset"],
    description: "Clear conversation",
    action: { kind: "client" as const, run: vi.fn() },
  };
  view.rerender(
    <SlashCommandPalette
      commands={[command]}
      selectedIndex={0}
      onSelectIndex={select}
      onPick={pick}
    />,
  );
  fireEvent.mouseEnter(screen.getByText("/clear"));
  fireEvent.mouseDown(screen.getByText("/clear"));
  expect(select).toHaveBeenCalledWith(0);
  expect(pick).toHaveBeenCalledWith(command);
});
