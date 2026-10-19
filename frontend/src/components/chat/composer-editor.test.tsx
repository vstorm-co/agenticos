import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Mentionable } from "@/types/mention";
import { ComposerEditor, messageOf, type ComposerEditorHandle } from "./composer-editor";

vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => <span /> }));

const NOTION: Mentionable = { kind: "mcp", id: "n", name: "Notion" };

/** The editor under a parent that holds its message, as the composer does. */
function Harness({
  initial = "",
  mentions = [],
  onCaret,
  handle,
  disabled,
}: {
  initial?: string;
  mentions?: Mentionable[];
  onCaret?: (caret: number) => void;
  handle?: React.Ref<ComposerEditorHandle>;
  disabled?: boolean;
}) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ComposerEditor
        ref={handle}
        value={value}
        mentions={mentions}
        onChange={(text, caret) => {
          setValue(text);
          onCaret?.(caret);
        }}
        placeholder="Type a message..."
        disabled={disabled}
      />
      <button type="button" onClick={() => setValue("set from outside")}>
        outside
      </button>
    </>
  );
}

const box = () => screen.getByRole("textbox", { name: "Type a message..." });
const chips = (kind: string) =>
  [...box().querySelectorAll<HTMLElement>(`[data-chip="${kind}"]`)].map(
    (chip) => chip.dataset.text,
  );

describe("the composer's editor", () => {
  it("shows its placeholder only while empty", async () => {
    render(<Harness />);
    expect(screen.getByText("Type a message...")).toBeInTheDocument();
    await userEvent.type(box(), "hi");
    expect(screen.queryByText("Type a message...")).toBeNull();
    expect(messageOf(box())).toBe("hi");
  });

  it("shows what it suggests until it is focused, then the placeholder", () => {
    render(
      <ComposerEditor
        value=""
        mentions={[]}
        onChange={vi.fn()}
        placeholder="Type a message..."
        idle={<p>try @Notion</p>}
      />,
    );
    expect(screen.getByText("try @Notion")).toBeInTheDocument();
    fireEvent.focus(box());
    expect(screen.queryByText("try @Notion")).toBeNull();
    expect(screen.getByText("Type a message...")).toBeInTheDocument();
    fireEvent.blur(box());
    expect(screen.getByText("try @Notion")).toBeInTheDocument();
  });

  it("makes an address a chip once something follows it, so it can still be typed", async () => {
    render(<Harness />);
    await userEvent.type(box(), "see https://github.com/acme/repo");
    expect(chips("link")).toEqual([]);

    await userEvent.type(box(), " now");
    expect(chips("link")).toEqual(["https://github.com/acme/repo"]);
    expect(messageOf(box())).toBe("see https://github.com/acme/repo now");
    const chip = box().querySelector('[data-chip="link"]')!;
    expect(chip).toHaveTextContent("github.com/acme/repo");
    expect(chip).toHaveAttribute("contenteditable", "false");
  });

  it("draws a picked mention as its name, and reads it back as the token", () => {
    render(<Harness initial="ask @Notion please" mentions={[NOTION]} />);
    expect(chips("mention")).toEqual(["@Notion"]);
    expect(box().querySelector('[data-chip="mention"]')).toHaveTextContent("Notion");
    expect(messageOf(box())).toBe("ask @Notion please");
  });

  it("takes a value set from outside, caret and all", async () => {
    const handle = createRef<ComposerEditorHandle>();
    render(<Harness handle={handle} />);
    act(() => handle.current!.focus());
    await userEvent.click(screen.getByRole("button", { name: "outside" }));
    expect(messageOf(box())).toBe("set from outside");
  });

  it("starts a new line on Enter and keeps a trailing one", async () => {
    const onCaret = vi.fn();
    render(<Harness onCaret={onCaret} />);
    await userEvent.type(box(), "one{Enter}");
    expect(messageOf(box())).toBe("one\n");
    // The browser draws a trailing break only with a line under it.
    expect(box().querySelector("br[data-sentinel]")).not.toBeNull();
    await userEvent.type(box(), "two");
    expect(messageOf(box())).toBe("one\ntwo");
    expect(onCaret).toHaveBeenLastCalledWith(7);
  });

  it("pastes and drops as plain text, never markup", async () => {
    render(<Harness />);
    await userEvent.click(box());
    await userEvent.paste("<b>bold</b>");
    expect(messageOf(box())).toBe("<b>bold</b>");
    expect(box().querySelector("b")).toBeNull();

    const transfer = { files: [], getData: () => " dropped" } as unknown as DataTransfer;
    fireEvent.drop(box(), { dataTransfer: transfer });
    expect(messageOf(box())).toBe("<b>bold</b> dropped");
  });

  it("leaves a dropped file to whoever handles files", () => {
    render(<Harness initial="x" />);
    const transfer = {
      files: [new File(["a"], "a.txt")],
      getData: () => "",
    } as unknown as DataTransfer;
    expect(fireEvent.drop(box(), { dataTransfer: transfer })).toBe(true);
    expect(messageOf(box())).toBe("x");
  });

  it("does nothing on a formatting shortcut", () => {
    render(<Harness initial="x" />);
    expect(fireEvent.keyDown(box(), { key: "b", metaKey: true })).toBe(false);
    expect(fireEvent.keyDown(box(), { key: "B", ctrlKey: true })).toBe(false);
    expect(fireEvent.keyDown(box(), { key: "a" })).toBe(true);
  });

  it("waits for an input method to finish before reading what it wrote", () => {
    const onCaret = vi.fn();
    render(<Harness onCaret={onCaret} />);
    fireEvent.compositionStart(box());
    box().textContent = "にほ";
    fireEvent.input(box());
    expect(onCaret).not.toHaveBeenCalled();
    // A value set from outside mid-composition waits too: the DOM is the input method's.
    fireEvent.click(screen.getByRole("button", { name: "outside" }));
    expect(box().textContent).toBe("にほ");
    box().textContent = "日本";
    fireEvent.compositionEnd(box());
    expect(messageOf(box())).toBe("日本");
    expect(onCaret).toHaveBeenCalledOnce();
  });

  it("puts the caret after a chip that spans the offset it is asked for", () => {
    const handle = createRef<ComposerEditorHandle>();
    render(<Harness handle={handle} initial="ask @Notion now" mentions={[NOTION]} />);
    act(() => handle.current!.setCaret(6));
    const selection = window.getSelection()!;
    // Right after the chip: the editor's third child is the text that follows it.
    expect(selection.focusNode).toBe(box());
    expect(selection.focusOffset).toBe(2);

    act(() => handle.current!.setCaret(2));
    expect(selection.focusNode?.textContent).toBe("ask ");
    expect(selection.focusOffset).toBe(2);

    act(() => handle.current!.setCaret(99));
    expect(selection.focusNode).toBe(box());
  });

  it("reads what a browser wrapped in blocks and breaks as lines", () => {
    render(<Harness />);
    box().innerHTML = "<div>one</div><div>two<br>three</div><p>four</p><!-- x --><br>";
    fireEvent.input(box());
    expect(messageOf(box())).toBe("one\ntwo\nthree\nfour");
  });

  it("reads a chip that names nothing as nothing", () => {
    render(<Harness />);
    box().innerHTML = 'a<span data-chip="mention">ghost</span>b';
    fireEvent.input(box());
    expect(messageOf(box())).toBe("ab");
  });

  it("hands a paste and a key to the composer first, and leaves what it took", async () => {
    const onPaste = vi.fn((event: React.ClipboardEvent) => event.preventDefault());
    const onKeyDown = vi.fn((event: React.KeyboardEvent) => event.preventDefault());
    function Taken() {
      const [value, setValue] = useState("");
      return (
        <ComposerEditor
          value={value}
          mentions={[]}
          onChange={setValue}
          onPaste={onPaste}
          onKeyDown={onKeyDown}
          placeholder="Type a message..."
        />
      );
    }
    render(<Taken />);
    await userEvent.click(box());
    await userEvent.paste("a whole document");
    expect(onPaste).toHaveBeenCalledOnce();
    expect(messageOf(box())).toBe("");
    // A key the composer took - a menu's Enter - is not also a new line.
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(messageOf(box())).toBe("");
  });

  it("writes at the end when the caret is somewhere else on the page", () => {
    const onCaret = vi.fn();
    render(<Harness initial="start" onCaret={onCaret} />);
    window.getSelection()!.removeAllRanges();
    const transfer = { files: [], getData: () => " end" } as unknown as DataTransfer;
    fireEvent.drop(box(), { dataTransfer: transfer });
    expect(messageOf(box())).toBe("start end");

    fireEvent.compositionStart(box());
    fireEvent.compositionEnd(box());
    expect(onCaret).toHaveBeenLastCalledWith(9);
  });

  it("keeps the caret where it was when typing rebuilds the chips", async () => {
    const onCaret = vi.fn();
    render(<Harness onCaret={onCaret} />);
    await userEvent.type(box(), "https://a.io then");
    expect(chips("link")).toEqual(["https://a.io"]);
    expect(onCaret).toHaveBeenLastCalledWith(17);
    await userEvent.keyboard("!");
    expect(messageOf(box())).toBe("https://a.io then!");
  });

  it("steps over a trailing break to the end", () => {
    const handle = createRef<ComposerEditorHandle>();
    render(<Harness handle={handle} initial={"one\n"} />);
    act(() => handle.current!.setCaret(10));
    expect(window.getSelection()!.focusNode).toBe(box());
  });

  it("is not editable while disabled", () => {
    render(<Harness disabled />);
    expect(box()).toHaveAttribute("contenteditable", "false");
    expect(box()).toHaveAttribute("aria-disabled", "true");
  });

  it("does nothing when asked after it is gone", () => {
    const handle = createRef<ComposerEditorHandle>();
    const { unmount } = render(<Harness handle={handle} />);
    const held = handle.current!;
    unmount();
    expect(() => {
      held.focus();
      held.setCaret(1);
    }).not.toThrow();
  });
});
