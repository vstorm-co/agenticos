import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DraftCardView, TurnDrafts } from "./draft-card";
import { type DraftCard, type DraftField } from "@/lib/drafts";
import type { ToolCall } from "@/types";

const writeText = vi.fn().mockResolvedValue(undefined);
const write = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  writeText.mockClear();
  write.mockClear();
  vi.stubGlobal("navigator", { clipboard: { writeText, write } });
});

function field(overrides: Partial<DraftField> = {}): DraftField {
  return { name: null, text: "Hi Marta,", format: "text", ...overrides };
}

function card(fields: DraftField[], extra: Partial<DraftCard> = {}): DraftCard {
  return {
    id: "tc-1",
    title: "Reply to Marta",
    kind: "email",
    versions: [{ label: null, fields }],
    ...extra,
  };
}

describe("a draft card", () => {
  it("copies each field on its own, as plain text", async () => {
    const body = "\n\nHi Marta,\n\nBest\n";
    render(
      <DraftCardView
        card={card([
          field({ name: "Subject", text: "Re: Q4 deck" }),
          field({ name: "Body", text: body }),
        ])}
      />,
    );

    const buttons = screen.getAllByRole("button", { name: "Copy to clipboard" });
    expect(buttons).toHaveLength(2);
    await userEvent.click(buttons[1]!);

    expect(writeText).toHaveBeenCalledWith("Hi Marta,\n\nBest");
    expect(write).not.toHaveBeenCalled();
  });

  it("shows the full kind on hover, where it is cut short", () => {
    render(<DraftCardView card={card([field({ name: "Body" })], { kind: "slack message" })} />);

    expect(screen.getByText("slack message").getAttribute("title")).toBe("slack message");
  });

  it("names a field only when its version has several", () => {
    render(<DraftCardView card={card([field({ name: "Body" })])} />);

    expect(screen.queryByText("Body")).toBeNull();
    expect(screen.queryByRole("tablist")).toBeNull();
  });

  it("shows the field names of a multi-field version", () => {
    render(
      <DraftCardView
        card={card([field({ name: "Subject", text: "a" }), field({ name: "Body", text: "b" })])}
      />,
    );

    expect(screen.getByText("Subject")).toBeVisible();
    expect(screen.getByText("Body")).toBeVisible();
  });

  it("shows the versions as tabs and one at a time", () => {
    render(
      <DraftCardView
        card={card([], {
          versions: [
            { label: "Short", fields: [field({ text: "Hi." })] },
            { label: "With details", fields: [field({ text: "Hi Marta, the deck is attached." })] },
          ],
        })}
      />,
    );

    expect(screen.getByRole("tablist", { name: "Versions of this draft" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Short" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("Hi Marta, the deck is attached.")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "With details" }));

    expect(screen.getByText("Hi Marta, the deck is attached.")).toBeVisible();
    expect(screen.queryByText("Hi.")).toBeNull();
  });

  it("follows the tabs pattern: one tab in the order, arrows move and wrap, the panel is named", async () => {
    render(
      <DraftCardView
        card={card([], {
          versions: [
            { label: "Short", fields: [field({ text: "Hi." })] },
            { label: "Long", fields: [field({ text: "Hello there." })] },
          ],
        })}
      />,
    );
    const [short, long] = screen.getAllByRole("tab");
    expect(short).toHaveAttribute("tabindex", "0");
    expect(long).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("tabpanel", { name: "Short" })).toHaveAttribute(
      "id",
      short!.getAttribute("aria-controls"),
    );

    short!.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(long).toHaveAttribute("aria-selected", "true");
    expect(long).toHaveFocus();
    expect(screen.getByRole("tabpanel", { name: "Long" })).toHaveTextContent("Hello there.");

    await userEvent.keyboard("{ArrowRight}");
    expect(short).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowLeft}");
    expect(long).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Home}");
    expect(long).toHaveAttribute("aria-selected", "true");
  });

  it("falls back to a numbered tab for an unlabelled version", () => {
    render(
      <DraftCardView
        card={card([], {
          versions: [
            { label: null, fields: [field({ text: "a" })] },
            { label: null, fields: [field({ text: "b" })] },
          ],
        })}
      />,
    );

    expect(screen.getByRole("tab", { name: "2" })).toBeVisible();
  });

  it("hints the format of each part", () => {
    render(
      <DraftCardView
        card={card([field({ text: "a" }), field({ text: "print(1)", format: "python" })])}
      />,
    );

    expect(screen.getByText("text")).toBeVisible();
    expect(screen.getByText("python")).toBeVisible();
  });

  it("shows markup as typed in a text field", () => {
    const text = "**bold** <b>hi</b>";
    const { container } = render(<DraftCardView card={card([field({ text })])} />);

    expect(screen.getByText(text)).toBeVisible();
    expect(container.querySelector("strong, b")).toBeNull();
  });

  it("shows a placeholder in the red token, brackets kept", () => {
    const { container } = render(
      <DraftCardView card={card([field({ text: "<b>hi</b> [Your Name]" })])} />,
    );

    const mark = screen.getByText("[Your Name]");
    expect(mark.tagName).toBe("MARK");
    expect(mark.className).toContain("--draft-placeholder-ink");
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText(/<b>hi<\/b>/)).toBeVisible();
  });

  it("copies the brackets as typed", async () => {
    render(<DraftCardView card={card([field({ text: "Thanks,\n[Your Name]" })])} />);

    await userEvent.click(screen.getByRole("button"));
    expect(writeText).toHaveBeenCalledWith("Thanks,\n[Your Name]");
  });

  it("marks nothing in a code field", () => {
    const { container } = render(
      <DraftCardView card={card([field({ text: "items[i]", format: "python" })])} />,
    );

    expect(container.querySelector("mark")).toBeNull();
  });

  it("keeps a field without a placeholder as one text child", () => {
    render(<DraftCardView card={card([field({ text: "Hi Marta," })])} />);

    const paragraph = screen.getByText("Hi Marta,");
    expect(paragraph.childNodes).toHaveLength(1);
    expect(paragraph.querySelector("mark")).toBeNull();
  });

  it("fills its column instead of sizing to its content", () => {
    const { container } = render(<DraftCardView card={card([field({})])} />);
    expect(container.firstElementChild).toHaveClass("w-full", "min-w-0");
  });

  it("wraps a long unbroken string inside the card", () => {
    render(<DraftCardView card={card([field({ text: "x".repeat(2000) })])} />);

    const text = screen.getByText("x".repeat(2000));
    expect(text).toHaveClass("whitespace-pre-wrap", "break-words");
    expect(text.closest("[data-draft-segment]")).toHaveClass("min-w-0");
  });
});

describe("the drafts of a turn", () => {
  const call: ToolCall = {
    id: "tc-1",
    name: "write_draft",
    presentation_kind: "draft",
    status: "completed",
    result: "Drafted Reply.",
    args: { title: "Reply", kind: "email", versions: [{ fields: [{ text: "Hi Marta," }] }] },
  };

  it("draws a card for each completed call", () => {
    render(<TurnDrafts calls={[call]} />);

    expect(screen.getByText("Reply")).toBeVisible();
    expect(screen.getByText("Hi Marta,")).toBeVisible();
  });

  it("draws nothing for a refusal or for no calls", () => {
    const { container } = render(
      <TurnDrafts calls={[{ ...call, result: "Each version needs a label." }]} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});

describe("previewing a markdown part", () => {
  const md = "# Title\n\n**bold** text";
  const mdCard = (text = md) => card([field({ text, format: "markdown" })]);

  it("shows the source first, renders on Preview and returns on Source", async () => {
    const { container } = render(<DraftCardView card={mdCard()} />);
    expect(container.querySelector("h1, strong")).toBeNull();
    expect(screen.getByText(/# Title/)).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Title" })).toBeVisible();
    expect(container.querySelector("strong")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(container.querySelector("h1, strong")).toBeNull();
    expect(screen.getByRole("button", { name: "Preview" })).toBeVisible();
  });

  it("copies the source in both views, with one copy button in a code fence", async () => {
    render(<DraftCardView card={mdCard("# Title\n\n```\ncode\n```")} />);
    await userEvent.click(screen.getAllByRole("button", { name: "Copy to clipboard" })[0]!);
    expect(writeText).toHaveBeenLastCalledWith("# Title\n\n```\ncode\n```");
    writeText.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByRole("heading", { level: 1 });

    const copy = screen.getAllByRole("button", { name: /^Cop/ });
    expect(copy).toHaveLength(1);
    await userEvent.click(copy[0]!);
    expect(writeText).toHaveBeenCalledWith("# Title\n\n```\ncode\n```");
  });

  it("clears the toggle by the name when named, by top padding when not", async () => {
    const { container } = render(
      <DraftCardView
        card={card([
          field({ name: "Subject", text: "Hi", format: "markdown" }),
          field({ text: "Body", format: "markdown" }),
        ])}
      />,
    );
    const [named, bare] = Array.from(container.querySelectorAll("[data-draft-segment]"));
    expect(screen.getByText("Subject").className).toContain("pr-36");
    expect(named!.querySelector("p:not(.text-muted-foreground)")!.className).not.toContain("pt-8");
    expect(bare!.querySelector("p")!.className).toContain("pt-8");
    for (const button of screen.getAllByRole("button", { name: "Preview" })) {
      await userEvent.click(button);
    }
    expect(named!.querySelector("div.min-w-0")!.className).not.toContain("pt-8");
    expect(bare!.querySelector("div.min-w-0")!.className).toContain("pt-8");
  });

  it("loads no image and interprets no raw HTML in the preview", async () => {
    const { container } = render(
      <DraftCardView card={mdCard("# Hi\n\n![x](https://tracker.example/p.png) <b>hi</b>")} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByRole("heading", { level: 1 });

    expect(container.querySelector("img, b")).toBeNull();
    expect(screen.getByText(/<b>hi<\/b>/)).toBeVisible();
    expect(screen.getByRole("link", { name: /x/ })).toHaveAttribute(
      "href",
      "https://tracker.example/p.png",
    );
  });

  it("offers no toggle on a text or a python part", () => {
    render(<DraftCardView card={card([field(), field({ text: "x = 1", format: "python" })])} />);

    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();
  });

  it("previews one part at a time", async () => {
    render(
      <DraftCardView
        card={card([
          field({ name: "A", text: "# One", format: "markdown" }),
          field({ name: "B", text: "# Two", format: "markdown" }),
        ])}
      />,
    );
    await userEvent.click(screen.getAllByRole("button", { name: "Preview" })[0]!);

    await screen.findByRole("heading", { level: 1, name: "One" });
    expect(screen.getByText("# Two")).toBeVisible();
  });

  it("returns to the source when another version is opened", async () => {
    render(
      <DraftCardView
        card={card([], {
          versions: [
            { label: "A", fields: [field({ text: "# One", format: "markdown" })] },
            { label: "B", fields: [field({ text: "# Two", format: "markdown" })] },
          ],
        })}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByRole("heading", { level: 1, name: "One" });

    await userEvent.click(screen.getByRole("tab", { name: "B" }));
    expect(screen.getByText("# Two")).toBeVisible();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });
});
