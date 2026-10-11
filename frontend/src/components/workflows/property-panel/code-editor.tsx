"use client";

import hljs from "highlight.js/lib/core";
import javascript from "highlight.js/lib/languages/javascript";
import python from "highlight.js/lib/languages/python";
import {
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type UIEvent,
} from "react";
import { useTranslations } from "next-intl";

import {
  type CodeLanguage,
  type Edit,
  argKeyAt,
  completeArg,
  erasePair,
  indent,
  matchingBracket,
  newline,
  typePair,
} from "@/lib/workflows/code-editing";
import { cn } from "@/lib/utils";

hljs.registerLanguage("python", python);
hljs.registerLanguage("javascript", javascript);

/** The rows the editor opens at, and grows to before it scrolls. */
const MIN_ROWS = 8;
const MAX_ROWS = 28;

/**
 * A code field for a Python or JavaScript step: highlighted as it is typed, with
 * the keys a code editor has - Tab and Shift+Tab indent, Enter keeps the
 * indentation, brackets and quotes close themselves, the bracket beside the
 * caret is marked with its match - and the keys of the bound `args` offered as
 * they are typed.
 *
 * Drawn the way `CodeArea` is: the highlighted copy underneath, the real
 * textarea on top with invisible text, the two kept in register by the same
 * font, padding and scroll. Tab is the editor's until Escape is pressed, and
 * then the next Tab leaves it, so the field never traps the keyboard.
 */
export function CodeEditor({
  id,
  language,
  value,
  onChange,
  label,
  placeholder,
  disabled,
  argKeys,
}: {
  id: string;
  language: CodeLanguage;
  value: string;
  onChange: (next: string) => void;
  label: string;
  placeholder?: string;
  disabled?: boolean;
  /** The keys of the bound `args`, offered as a key is typed. */
  argKeys: readonly string[];
}) {
  const t = useTranslations("workflows");
  const listId = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  const underlay = useRef<HTMLPreElement>(null);
  const marks = useRef<HTMLPreElement>(null);
  const pending = useRef<{ start: number; end: number } | null>(null);
  const [released, setReleased] = useState(false);
  const [caret, setCaret] = useState<number | null>(null);
  const [active, setActive] = useState(0);

  const html = useMemo(
    () => hljs.highlight(`${value}\n`, { language, ignoreIllegals: true }).value,
    [value, language],
  );
  const typing = caret === null ? null : argKeyAt(value, caret, language);
  const pair = caret === null ? null : matchingBracket(value, caret);
  // Each key offered with the edit that completes it, worked out while the
  // caret and the key being typed are known.
  const offered =
    typing === null || caret === null
      ? []
      : argKeys
          .filter((key) => key.startsWith(typing.prefix) && key !== typing.prefix)
          .map((key) => ({ key, edit: completeArg(value, caret, typing, key) }));
  const open = offered.length > 0;
  const rows = Math.min(MAX_ROWS, Math.max(MIN_ROWS, value.split("\n").length + 1));

  useLayoutEffect(() => {
    const target = pending.current;
    if (target === null || area.current === null) return;
    area.current.setSelectionRange(target.start, target.end);
    pending.current = null;
  }, [value]);

  const apply = (edit: Edit) => {
    setCaret(edit.end);
    if (edit.text === value) {
      // Stepping over a closer changes no text, so no render will place the caret.
      area.current?.setSelectionRange(edit.start, edit.end);
      return;
    }
    pending.current = { start: edit.start, end: edit.end };
    onChange(edit.text);
  };

  const pick = (edit: Edit) => {
    apply(edit);
    setActive(0);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const { selectionStart: start, selectionEnd: end } = event.currentTarget;
    const edit: Edit = { text: value, start, end };
    if (open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((active + step + offered.length) % offered.length);
      return;
    }
    if (open && (event.key === "Enter" || event.key === "Tab")) {
      event.preventDefault();
      const chosen = offered[Math.min(active, offered.length - 1)];
      if (chosen !== undefined) pick(chosen.edit);
      return;
    }
    if (event.key === "Escape") {
      setReleased(true);
      setCaret(null);
      return;
    }
    if (event.key === "Tab" && !released && !event.altKey && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      apply(indent(edit, language, event.shiftKey));
      return;
    }
    setReleased(false);
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const next =
      event.key === "Enter"
        ? newline(edit, language)
        : event.key === "Backspace"
          ? erasePair(edit)
          : event.key.length === 1
            ? typePair(edit, event.key)
            : null;
    if (next === null) return;
    event.preventDefault();
    apply(next);
  };

  const sync = (event: UIEvent<HTMLTextAreaElement>) => {
    for (const pane of [underlay.current, marks.current]) {
      if (pane !== null) {
        pane.scrollTop = event.currentTarget.scrollTop;
        pane.scrollLeft = event.currentTarget.scrollLeft;
      }
    }
  };

  const shared = "p-3 font-mono text-xs leading-5 whitespace-pre-wrap break-words";

  return (
    <div className="space-y-1.5">
      <div
        className={cn(
          "border-input focus-within:ring-ring/50 relative rounded-md border focus-within:ring-[3px]",
          disabled && "opacity-60",
        )}
        style={{ height: `calc(${rows} * 1.25rem + 1.5rem)` }}
      >
        <pre
          ref={underlay}
          aria-hidden
          className={cn(shared, "hljs pointer-events-none absolute inset-0 m-0 overflow-hidden")}
          // highlight.js escapes what it highlights; nothing here hands it markup.
          dangerouslySetInnerHTML={{ __html: html }}
        />
        {pair !== null && (
          // The same text again, invisible, with the two brackets boxed: laid
          // over the highlighting so it keeps its colours.
          <pre
            ref={(pane) => {
              marks.current = pane;
              // Mounted as the caret reaches a bracket, into a field that may be
              // scrolled already.
              if (pane !== null && area.current !== null) {
                pane.scrollTop = area.current.scrollTop;
                pane.scrollLeft = area.current.scrollLeft;
              }
            }}
            aria-hidden
            data-testid="bracket-match"
            className={cn(
              shared,
              "pointer-events-none absolute inset-0 m-0 overflow-hidden text-transparent",
            )}
          >
            {value.slice(0, pair[0])}
            <mark className="ring-foreground/40 rounded-[2px] bg-transparent text-transparent ring-1">
              {value[pair[0]]}
            </mark>
            {value.slice(pair[0] + 1, pair[1])}
            <mark className="ring-foreground/40 rounded-[2px] bg-transparent text-transparent ring-1">
              {value[pair[1]]}
            </mark>
            {`${value.slice(pair[1] + 1)}\n`}
          </pre>
        )}
        <textarea
          ref={area}
          id={id}
          value={value}
          aria-label={label}
          aria-autocomplete="list"
          aria-controls={open ? listId : undefined}
          aria-activedescendant={open ? `${listId}-${active}` : undefined}
          placeholder={placeholder}
          disabled={disabled}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          onChange={(event) => {
            setCaret(event.target.selectionEnd);
            onChange(event.target.value);
          }}
          onSelect={(event) => setCaret(event.currentTarget.selectionEnd)}
          onKeyDown={onKeyDown}
          onBlur={() => setCaret(null)}
          onScroll={sync}
          className={cn(
            shared,
            "caret-foreground text-foreground/0 placeholder:text-muted-foreground absolute inset-0 h-full w-full resize-none overflow-auto bg-transparent outline-none",
          )}
        />
      </div>
      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-label={t("codeArgKeys")}
          className="border-border bg-popover flex flex-wrap gap-1 rounded-md border p-1"
        >
          {offered.map(({ key, edit }, index) => (
            <li
              key={key}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className={cn(
                "cursor-pointer rounded px-2 py-0.5 font-mono text-xs",
                index === active ? "bg-accent text-accent-foreground" : "text-muted-foreground",
              )}
              // Before the textarea blurs, so the caret the key completes at is kept.
              onMouseDown={(event) => {
                event.preventDefault();
                pick(edit);
              }}
            >
              {key}
            </li>
          ))}
        </ul>
      )}
      <p className="text-muted-foreground text-xs">{t("codeKeysHint")}</p>
    </div>
  );
}
