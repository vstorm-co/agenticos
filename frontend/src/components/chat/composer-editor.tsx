"use client";

import {
  useCallback,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
} from "react";
import { createPortal } from "react-dom";

import { readableLink, richSegments } from "@/lib/rich-text";
import { cn } from "@/lib/utils";
import type { Mentionable } from "@/types/mention";

import { LinkFavicon } from "./link-favicon";
import { MentionMark } from "./mention-chip";

/** What the composer can ask of the editor it types into. */
export interface ComposerEditorHandle {
  focus: () => void;
  /** Put the caret `offset` characters into the message, after a chip that spans it. */
  setCaret: (offset: number) => void;
}

/**
 * One run of the message as the editor draws it. A mention is always a chip; an
 * address becomes one once something follows it, so it can still be typed.
 */
type Piece =
  | { kind: "text"; text: string }
  | { kind: "mention"; text: string; item: Mentionable }
  | { kind: "link"; text: string; url: string };

function piecesOf(value: string, mentions: readonly Mentionable[]): Piece[] {
  let offset = 0;
  const pieces: Piece[] = [];
  for (const segment of richSegments(value, mentions)) {
    offset += segment.text.length;
    const settled = /\s/.test(value.charAt(offset));
    const piece: Piece = segment.item
      ? { kind: "mention", text: segment.text, item: segment.item }
      : segment.url && settled
        ? { kind: "link", text: segment.text, url: segment.url }
        : { kind: "text", text: segment.text };
    const last = pieces.at(-1);
    if (piece.kind === "text" && last?.kind === "text") last.text += piece.text;
    else pieces.push(piece);
  }
  return pieces;
}

const CHIP = "data-chip";
const SENTINEL = "data-sentinel";

/** What a chip stands for in the message - the token or address it was drawn from. */
function chipText(chip: HTMLElement): string {
  return chip.dataset.text ?? "";
}

/**
 * The message a run of the editor's DOM holds, and the shape of it.
 *
 * A text node is its text; a chip is what it stands for; a `<br>` is a line
 * break unless it is ours (the sentinel) or the browser's placeholder after a
 * chip left last - `trailingBreak` says whether a last `<br>` can be a real one,
 * which it can in the slice of the editor before the caret.
 */
function read(root: Node, trailingBreak = false): { text: string; shape: string } {
  let text = "";
  const shape: string[] = [];
  const plain = (data: string) => {
    text += data;
    if (shape.at(-1) !== "t") shape.push("t");
  };
  const walk = (node: Node, first: boolean) => {
    if (node instanceof Text) return plain(node.data.replace(/\u00a0/g, " "));
    // A comment, or anything else that is not text or an element, says nothing.
    if (!(node instanceof HTMLElement)) return;
    const kind = node.getAttribute(CHIP);
    if (kind !== null) {
      text += chipText(node);
      shape.push(`${kind}:${chipText(node)}`);
      return;
    }
    if (node.tagName === "BR") {
      const placeholder = node === root.lastChild && !trailingBreak;
      if (!node.hasAttribute(SENTINEL) && !placeholder) plain("\n");
      return;
    }
    // A block a browser wrapped a line in: a new line before it, unless first.
    if ((node.tagName === "DIV" || node.tagName === "P") && !first) plain("\n");
    node.childNodes.forEach((child, index) => walk(child, index === 0));
  };
  root.childNodes.forEach((child, index) => walk(child, index === 0));
  return { text, shape: shape.join("|") };
}

/** The message an editor holds - its text, each chip read as what it stands for. */
export function messageOf(root: HTMLElement): string {
  return read(root).text;
}

function shapeOf(pieces: readonly Piece[]): string {
  return pieces
    .map((piece) => (piece.kind === "text" ? "t" : `${piece.kind}:${piece.text}`))
    .join("|");
}

/** How many characters of the message come before `node` at `nodeOffset`: the slice of the DOM before it, read. */
function offsetOf(root: HTMLElement, node: Node, nodeOffset: number): number {
  const range = document.createRange();
  range.setStart(root, 0);
  range.setEnd(node, nodeOffset);
  return read(range.cloneContents(), true).text.length;
}

function select(range: Range) {
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

/** Put the caret `offset` characters in, after a chip that spans it, or at the end. */
function placeCaret(root: HTMLElement, offset: number) {
  const range = document.createRange();
  let left = offset;
  for (const child of Array.from(root.childNodes)) {
    const chip = child instanceof HTMLElement && child.hasAttribute(CHIP);
    const size =
      child instanceof Text ? child.data.length : chip ? chipText(child as HTMLElement).length : 0;
    if (left <= size && (child instanceof Text || chip)) {
      if (child instanceof Text) range.setStart(child, left);
      else range.setStartAfter(child);
      range.collapse(true);
      return select(range);
    }
    left -= size;
  }
  range.selectNodeContents(root);
  range.collapse(false);
  select(range);
}

/** Where the caret is in the message, or null when it is not in the editor. */
function caretIn(root: HTMLElement): number | null {
  const selection = window.getSelection();
  const node = selection?.focusNode;
  if (!selection || !node || !root.contains(node)) return null;
  return offsetOf(root, node, selection.focusOffset);
}

interface ChipHost {
  element: HTMLElement;
  piece: Exclude<Piece, { kind: "text" }>;
}

/**
 * The composer's text box: plain text with real chips in it.
 *
 * The message stays one string - `@Name` for a mention, the address for a link -
 * so sending, the slash palette and the server read exactly what they did. The
 * editor draws that string as text and chips, rebuilding its DOM only when the
 * shape changes (a mention picked, a space typed after an address) and putting
 * the caret back where it was; ordinary typing is the browser's.
 *
 * A chip is `contenteditable=false`: the caret steps over it, Backspace takes it
 * whole, and no spelling squiggle ever lands under a name. Pasted or dropped
 * content arrives as plain text, and formatting shortcuts do nothing, so the
 * DOM never holds anything the message cannot say.
 */
export function ComposerEditor({
  value,
  mentions,
  onChange,
  onKeyDown,
  onPaste,
  placeholder,
  idle,
  disabled = false,
  enterKeyHint,
  className,
  ref,
}: {
  value: string;
  mentions: readonly Mentionable[];
  /** The new message and where the caret is in it. */
  onChange: (text: string, caret: number) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => void;
  onPaste?: (event: ClipboardEvent<HTMLDivElement>) => void;
  placeholder: string;
  /** Shown instead of the placeholder while the box is empty and not being typed in. */
  idle?: ReactNode;
  disabled?: boolean;
  enterKeyHint?: "enter" | "send";
  className?: string;
  ref?: Ref<ComposerEditorHandle>;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [hosts, setHosts] = useState<ChipHost[]>([]);
  // What this editor last reported, and where its caret was then: a rebuild for
  // a value it reported itself (a space typed after an address) keeps the caret;
  // one for a value set from outside (a send, a slash command, dictation) puts
  // it at the end.
  const reported = useRef<{ text: string; caret: number } | null>(null);
  const composing = useRef(false);
  const [focused, setFocused] = useState(false);

  const emit = useCallback(
    (text: string, caret: number) => {
      reported.current = { text, caret };
      onChange(text, caret);
    },
    [onChange],
  );

  useImperativeHandle(ref, () => ({
    focus: () => rootRef.current?.focus(),
    setCaret: (offset: number) => {
      const root = rootRef.current;
      if (root === null) return;
      root.focus();
      placeCaret(root, offset);
    },
  }));

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (root === null || composing.current) return;
    const pieces = piecesOf(value, mentions);
    const held = read(root);
    if (held.text === value && held.shape === shapeOf(pieces)) return;
    const focused = document.activeElement === root;
    const keep = reported.current?.text === value ? reported.current.caret : value.length;
    root.replaceChildren();
    const nextHosts: ChipHost[] = [];
    for (const piece of pieces) {
      if (piece.kind === "text") {
        root.appendChild(document.createTextNode(piece.text));
        continue;
      }
      const chip = document.createElement("span");
      chip.setAttribute(CHIP, piece.kind);
      chip.dataset.text = piece.text;
      chip.setAttribute("contenteditable", "false");
      chip.className = CHIP_CLASS;
      root.appendChild(chip);
      nextHosts.push({ element: chip, piece });
    }
    // A trailing line break takes a line only when something follows it.
    if (value.endsWith("\n")) {
      const sentinel = document.createElement("br");
      sentinel.setAttribute(SENTINEL, "");
      root.appendChild(sentinel);
    }
    setHosts(nextHosts);
    if (focused) placeCaret(root, keep);
  }, [value, mentions]);

  /** Tell the composer what the editor now says, and where its caret is. */
  const report = (root: HTMLElement) => {
    const text = read(root).text;
    emit(text, caretIn(root) ?? text.length);
  };

  /** Put `text` where the caret is, through the message rather than the DOM. */
  const insert = (root: HTMLElement, text: string) => {
    const at = caretIn(root) ?? value.length;
    emit(value.slice(0, at) + text + value.slice(at), at + text.length);
  };

  return (
    <div className="relative">
      {value === "" &&
        (idle && !focused ? (
          idle
        ) : (
          <span
            aria-hidden
            className="text-muted-foreground pointer-events-none absolute inset-x-0 top-0 truncate py-2.5 text-base"
          >
            {placeholder}
          </span>
        ))}
      <div
        ref={rootRef}
        role="textbox"
        aria-multiline="true"
        aria-label={placeholder}
        aria-disabled={disabled || undefined}
        contentEditable={!disabled}
        tabIndex={disabled ? -1 : 0}
        suppressContentEditableWarning
        enterKeyHint={enterKeyHint}
        autoCapitalize="sentences"
        spellCheck
        className={cn(
          "relative block max-h-[200px] min-h-[40px] w-full scrollbar-thin overflow-y-auto py-2.5 text-base break-words whitespace-pre-wrap focus:outline-none",
          disabled && "cursor-not-allowed opacity-50",
          className,
        )}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onInput={(event) => {
          if (!composing.current) report(event.currentTarget);
        }}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onCompositionEnd={(event) => {
          composing.current = false;
          report(event.currentTarget);
        }}
        onKeyDown={(event) => {
          onKeyDown?.(event);
          if (event.defaultPrevented) return;
          // Formatting has nowhere to go in a plain message.
          if (
            (event.metaKey || event.ctrlKey) &&
            ["b", "i", "u"].includes(event.key.toLowerCase())
          ) {
            event.preventDefault();
            return;
          }
          if (event.key === "Enter") {
            event.preventDefault();
            insert(event.currentTarget, "\n");
          }
        }}
        onPaste={(event) => {
          onPaste?.(event);
          if (event.defaultPrevented) return;
          event.preventDefault();
          insert(event.currentTarget, event.clipboardData.getData("text/plain"));
        }}
        onDrop={(event) => {
          const text = event.dataTransfer.getData("text/plain");
          if (event.dataTransfer.files.length > 0 || text === "") return;
          event.preventDefault();
          insert(event.currentTarget, text);
        }}
      />
      {hosts.map((host, index) =>
        createPortal(<ChipFace piece={host.piece} />, host.element, `${index}:${host.piece.text}`),
      )}
    </div>
  );
}

const CHIP_CLASS =
  "bg-foreground/[0.07] text-foreground mx-px inline-flex max-w-[18rem] items-center gap-1 rounded-md px-1.5 align-baseline text-[0.95em] leading-6 font-medium select-none";

function ChipFace({ piece }: { piece: Exclude<Piece, { kind: "text" }> }) {
  if (piece.kind === "mention") {
    return (
      <>
        <MentionMark item={piece.item} className="h-4 w-4 text-[8px]" />
        <span className="truncate">{piece.item.name}</span>
      </>
    );
  }
  const { host, path } = readableLink(piece.url);
  return (
    <>
      <LinkFavicon url={piece.url} className="h-3.5 w-3.5" />
      <span className="truncate">
        {host}
        {path && <span className="text-muted-foreground font-normal">{path}</span>}
      </span>
    </>
  );
}
