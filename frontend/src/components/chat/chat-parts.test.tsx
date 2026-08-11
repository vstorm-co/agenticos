import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatEmptyState } from "./chat-empty-state";
import { CopyButton } from "./copy-button";
import { PendingMessages } from "./pending-messages";
import { SlashCommandPalette } from "./slash-command-palette";
import { ChartMessage, parseChartResult } from "./chart-message";
import { MarkdownContent } from "./markdown-content";
import { BUILTIN_COMMANDS, resolveBuiltin } from "./slash-commands";
import type { Translate } from "@/lib/agent-step-captions";
import messages from "../../../messages/en.json";

/**
 * The built-ins as the palette receives them: `BUILTIN_COMMANDS` holds keys, and the
 * copy is resolved where it is rendered. Cast because `createTranslator` types its key
 * against the message tree while `Translate` takes the string a table holds.
 */
const commands = BUILTIN_COMMANDS.map((command) =>
  resolveBuiltin(
    command,
    createTranslator({ locale: "en", messages, namespace: "chat.commands" }) as Translate,
  ),
);

const auth = vi.hoisted(() => ({
  user: null as { full_name?: string | null; email?: string } | null,
}));
vi.mock("@/hooks", () => ({ useAuth: () => ({ user: auth.user }) }));

beforeEach(() => {
  auth.user = null;
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/**
 * The small parts of the chat.
 *
 * Each is a component whose whole job is to say something precise about a state:
 * what is queued and cancellable, whether a copy landed, which command is about
 * to run. The states they must not misrepresent are the empty ones - a queue with
 * nothing in it renders nothing rather than an empty box, and a palette that
 * matched nothing says so rather than showing an unfiltered list.
 */
describe("copying to the clipboard", () => {
  it("copies the text it was given, and says so", async () => {
    render(<CopyButton text="npm install" />);

    await userEvent.click(screen.getByRole("button", { name: "Copy to clipboard" }));

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("npm install");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Copied to clipboard" })).toBeInTheDocument(),
    );
  });

  it("does not act on whatever it sits inside", async () => {
    // It lives on cards and rows that are themselves clickable; copying a code
    // block must not also open the panel behind it.
    const onParentClick = vi.fn();
    render(
      <button type="button" onClick={onParentClick}>
        <CopyButton text="x" />
      </button>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Copy to clipboard" }));

    expect(onParentClick).not.toHaveBeenCalled();
  });

  it("stays offering a copy when the clipboard refused", async () => {
    // Which is what a page served over plain HTTP answers; claiming "Copied" there
    // is a lie somebody acts on.
    vi.stubGlobal("navigator", {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    render(<CopyButton text="x" />);

    await userEvent.click(screen.getByRole("button", { name: "Copy to clipboard" }));

    expect(screen.getByRole("button", { name: "Copy to clipboard" })).toBeInTheDocument();
  });
});

describe("the queue above the composer", () => {
  const queued = [
    { id: "q-1", content: "First question" },
    { id: "q-2", content: "Second question", files: [{ id: "f-1" }, { id: "f-2" }] },
  ] as Parameters<typeof PendingMessages>[0]["messages"];

  it("renders nothing at all when nothing is queued", () => {
    // An empty bordered box above the composer reads as a broken layout.
    const { container } = render(<PendingMessages messages={[]} onCancel={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("numbers what is waiting, in the order it will be sent", () => {
    render(<PendingMessages messages={queued} onCancel={vi.fn()} />);

    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]!).getByText("1")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("First question")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("2")).toBeInTheDocument();
  });

  it("says a queued message carries attachments, and how many", () => {
    render(<PendingMessages messages={queued} onCancel={vi.fn()} />);

    expect(screen.getByText("2 files")).toBeInTheDocument();
  });

  it("uses the singular for one attachment, and says nothing for none", () => {
    render(
      <PendingMessages
        messages={
          [
            { id: "q-1", content: "one", files: [{ id: "f-1" }] },
            { id: "q-2", content: "none", files: [] },
          ] as Parameters<typeof PendingMessages>[0]["messages"]
        }
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText("1 file")).toBeInTheDocument();
    expect(screen.queryByText("0 files")).toBeNull();
  });

  it("cancels the entry whose button was pressed", async () => {
    // The whole reason the queue is visible: a message typed by mistake while the
    // agent was busy has to be retractable before it is sent.
    const onCancel = vi.fn();
    render(<PendingMessages messages={queued} onCancel={onCancel} />);

    const rows = screen.getAllByRole("listitem");
    await userEvent.click(within(rows[1]!).getByRole("button", { name: "Remove from queue" }));

    expect(onCancel).toHaveBeenCalledWith("q-2");
  });

  it("says when the queue will drain", () => {
    render(<PendingMessages messages={queued} onCancel={vi.fn()} />);

    expect(screen.getByText(/sends after current reply/)).toBeInTheDocument();
  });
});

describe("the slash command palette", () => {
  it("lists each command by name and description", () => {
    render(
      <SlashCommandPalette
        commands={commands}
        selectedIndex={0}
        onSelectIndex={vi.fn()}
        onPick={vi.fn()}
      />,
    );

    expect(screen.getByText("/clear")).toBeInTheDocument();
    expect(screen.getByText(commands[0]!.description)).toBeInTheDocument();
  });

  it("shows the first alias, which is the other word people type", () => {
    render(
      <SlashCommandPalette
        commands={commands}
        selectedIndex={0}
        onSelectIndex={vi.fn()}
        onPick={vi.fn()}
      />,
    );

    expect(screen.getByText("/reset")).toBeInTheDocument();
  });

  it("marks which row is about to run", () => {
    const { container } = render(
      <SlashCommandPalette
        commands={commands}
        selectedIndex={1}
        onSelectIndex={vi.fn()}
        onPick={vi.fn()}
      />,
    );

    const rows = container.querySelectorAll("li");
    expect(rows[1]).toHaveClass("bg-foreground/[0.06]");
    expect(rows[0]).not.toHaveClass("bg-foreground/[0.06]");
  });

  it("follows the mouse, so hover and the arrow keys agree", () => {
    const onSelectIndex = vi.fn();
    render(
      <SlashCommandPalette
        commands={commands}
        selectedIndex={0}
        onSelectIndex={onSelectIndex}
        onPick={vi.fn()}
      />,
    );

    fireEvent.mouseEnter(screen.getByText("/regen").closest("li")!);

    expect(onSelectIndex).toHaveBeenCalledWith(1);
  });

  it("runs a command on press without taking focus from the composer", () => {
    // `mousedown` with the default prevented, rather than a click: a click would
    // blur the textarea, and the palette exists to keep somebody typing.
    const onPick = vi.fn();
    render(
      <SlashCommandPalette
        commands={commands}
        selectedIndex={0}
        onSelectIndex={vi.fn()}
        onPick={onPick}
      />,
    );

    const event = fireEvent.mouseDown(screen.getByText("/clear").closest("li")!);

    expect(onPick).toHaveBeenCalledWith(commands[0]);
    // `fireEvent` returns false when a handler prevented the default.
    expect(event).toBe(false);
  });

  it("says nothing matched rather than showing an unfiltered list", () => {
    render(
      <SlashCommandPalette
        commands={[]}
        selectedIndex={0}
        onSelectIndex={vi.fn()}
        onPick={vi.fn()}
      />,
    );

    expect(screen.getByText(/No matching commands/)).toBeInTheDocument();
  });

  it("keeps the highlighted row in view as the selection moves", () => {
    // A palette scrolled past its own selection is a palette that looks empty.
    const scrollIntoView = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scrollIntoView;

    const { rerender } = render(
      <SlashCommandPalette
        commands={commands}
        selectedIndex={0}
        onSelectIndex={vi.fn()}
        onPick={vi.fn()}
      />,
    );
    rerender(
      <SlashCommandPalette
        commands={commands}
        selectedIndex={4}
        onSelectIndex={vi.fn()}
        onPick={vi.fn()}
      />,
    );

    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
    Element.prototype.scrollIntoView = original;
  });
});

describe("the empty chat", () => {
  it("greets somebody by their first name", () => {
    auth.user = { full_name: "Kacper Włodarczyk", email: "kacper@example.com" };

    render(<ChatEmptyState onPick={vi.fn()} />);

    expect(screen.getByText("How can I help, Kacper?")).toBeInTheDocument();
  });

  it("falls back to the local part of the address", () => {
    auth.user = { full_name: null, email: "kacper@example.com" };

    render(<ChatEmptyState onPick={vi.fn()} />);

    expect(screen.getByText("How can I help, kacper?")).toBeInTheDocument();
  });

  it("greets nobody in particular when it knows no name", () => {
    render(<ChatEmptyState onPick={vi.fn()} />);

    expect(screen.getByText("How can I help today?")).toBeInTheDocument();
  });

  it("sends the whole prompt, not the heading somebody clicked", async () => {
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);

    await userEvent.click(screen.getByText("Summarize my docs"));

    expect(onPick).toHaveBeenCalledWith(
      "Summarize the key points from my latest indexed documents.",
    );
  });

  it("names the agent that will answer", () => {
    render(<ChatEmptyState onPick={vi.fn()} agentLabel="@support" />);

    expect(screen.getByText(/Powered by @support/)).toBeInTheDocument();
  });
});

describe("recognising a chart", () => {
  it("reads the spec the chart tool returns", () => {
    const spec = { kind: "chart", chart_type: "bar", title: "Spend", series: [] };

    expect(parseChartResult(spec)).toEqual(spec);
    expect(parseChartResult(JSON.stringify(spec))).toEqual(spec);
  });

  it("refuses anything that is not one, so the raw renderer takes it", () => {
    // The check is static and synchronous on purpose: the caller decides whether
    // to render a chart *before* pulling in the charting library at all.
    expect(parseChartResult("not json")).toBeNull();
    expect(parseChartResult(JSON.stringify({ kind: "table" }))).toBeNull();
    expect(parseChartResult(null)).toBeNull();
    expect(parseChartResult(42)).toBeNull();
  });
});

/**
 * The two renderers that are split out of the bundle.
 *
 * Recharts and the Markdown stack are both large and both needed only when a
 * message actually contains one, so each is loaded on demand. What matters here
 * is the placeholder: it holds the space the real thing will take, so a chart
 * arriving mid-stream does not shove the transcript down the page.
 */
describe("the lazily-loaded renderers", () => {
  it("holds the chart's space while the charting library loads", () => {
    const { container } = render(
      <ChartMessage
        spec={{ kind: "chart", chart_type: "bar", title: "Spend", series: [] } as never}
      />,
    );

    // Same height as the chart card, so nothing jumps when it swaps in.
    expect(container.querySelector(".h-\\[300px\\]")).not.toBeNull();
  });

  it("renders the chart once the library arrives", async () => {
    render(
      <ChartMessage
        spec={
          {
            kind: "chart",
            chart_type: "bar",
            title: "Spend by month",
            series: [{ name: "Spend", points: [{ x: "Jan", y: 1 }] }],
          } as never
        }
      />,
    );

    expect(await screen.findByText("Spend by month")).toBeInTheDocument();
  });

  it("shows the streamed text until the Markdown renderer arrives, then renders it", async () => {
    render(<MarkdownContent content="# Refunds" />);

    expect(await screen.findByText("Refunds")).toBeInTheDocument();
  });
});
