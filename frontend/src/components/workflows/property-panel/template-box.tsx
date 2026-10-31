"use client";

import {
  forwardRef,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEventHandler,
  type KeyboardEvent,
  type UIEvent,
} from "react";

import { Input, Textarea } from "@/components/ui";
import {
  completePlaceholder,
  openPlaceholderAt,
  templateSegments,
} from "@/lib/workflows/template-text";
import { cn } from "@/lib/utils";

import { matchSuggestions, SuggestionList, type Suggestion } from "./template-suggest";

interface TemplateBoxProps {
  id: string;
  value: string;
  /** Several lines tall, for a message or a prompt; else one line. */
  multiline: boolean;
  /** A placeholder naming nothing in reach, drawn apart from the ones that do. */
  unknown: string | null;
  /** The steps' names, so a placeholder's step reads apart from its path. */
  stepNames: readonly string[];
  /** What a placeholder being written can name, offered under the box. */
  suggestions: readonly Suggestion[];
  disabled?: boolean;
  placeholder?: string;
  invalid: boolean;
  onChange: (value: string) => void;
  onBlur: FocusEventHandler;
}

/**
 * A text box whose `{{ ... }}` placeholders read as code, not as text: braces
 * quiet, the step named in one colour and the path into its output in another,
 * on a tint - and one naming nothing in reach in red, underlined. The colours
 * are the `--domain-*` tokens, which follow the console's theme switch; a
 * `dark:` class follows the operating system's instead.
 *
 * A text box cannot colour part of its own text, so the box stays a plain one
 * for typing, the caret and selection, with its letters made transparent; what
 * is seen is a copy laid out under it the same way, coloured. Only colour
 * differs between the two - same font, weight, padding, border, wrapping and a
 * reserved scrollbar gutter - so every letter of the copy sits under its own,
 * and the copy scrolls with the box.
 *
 * Typing `{{` opens a list of the values in reach, narrowed by what follows;
 * arrows move through it, Enter or Tab writes the placeholder out, closing
 * braces and all, and Escape puts it away until the next keystroke.
 */
export const TemplateBox = forwardRef<HTMLInputElement & HTMLTextAreaElement, TemplateBoxProps>(
  function TemplateBox(
    {
      id,
      value,
      multiline,
      unknown,
      stepNames,
      suggestions,
      disabled,
      placeholder,
      invalid,
      onChange,
      onBlur,
    },
    ref,
  ) {
    const backdrop = useRef<HTMLDivElement>(null);
    const own = useRef<(HTMLInputElement & HTMLTextAreaElement) | null>(null);
    const [caret, setCaret] = useState<number | null>(null);
    const [active, setActive] = useState(0);
    // The text the list was put away at: it stays away until that changes.
    const [dismissed, setDismissed] = useState<string | null>(null);
    // Where the caret goes once a picked placeholder has been written in.
    const placeCaret = useRef<number | null>(null);
    useLayoutEffect(() => {
      if (placeCaret.current === null || own.current === null) return;
      own.current.setSelectionRange(placeCaret.current, placeCaret.current);
      placeCaret.current = null;
    }, [value]);

    const writing = caret === null || disabled ? null : openPlaceholderAt(value, caret);
    const matches =
      writing === null || dismissed === value ? [] : matchSuggestions(suggestions, writing.query);
    const open = matches.length > 0;
    const shown = Math.min(active, matches.length - 1);
    const listId = `${id}-suggestions`;

    // A dialog around the box closes on Escape from a listener on the document,
    // in the capture phase - before the box's own keydown. One on the window runs
    // earlier still, and a handled Escape is one the dialog leaves alone.
    useEffect(() => {
      if (!open) return;
      const escape = (event: globalThis.KeyboardEvent) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        setDismissed(value);
      };
      window.addEventListener("keydown", escape, { capture: true });
      return () => window.removeEventListener("keydown", escape, { capture: true });
    }, [open, value]);

    // Only reached from the open list, which a placeholder being written opened.
    const pick = (suggestion: Suggestion) => {
      const at = caret as number;
      const start = (writing as { start: number }).start;
      const next = completePlaceholder(value, at, start, suggestion.text);
      // Text that does not change renders nothing to place the caret after.
      if (next.text === value) own.current?.setSelectionRange(next.caret, next.caret);
      else placeCaret.current = next.caret;
      setCaret(next.caret);
      onChange(next.text);
    };
    const keys = (event: KeyboardEvent) => {
      if (!open) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setActive((shown + step + matches.length) % matches.length);
      } else if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        pick(matches[shown] as Suggestion);
      }
    };
    const track = (event: { currentTarget: HTMLInputElement | HTMLTextAreaElement }) => {
      setCaret(event.currentTarget.selectionStart);
      setActive(0);
    };
    const follow = (event: UIEvent<HTMLElement>) => {
      // Mounted with the box, so it is there whenever the box scrolls.
      const copy = backdrop.current as HTMLDivElement;
      copy.scrollTop = event.currentTarget.scrollTop;
      copy.scrollLeft = event.currentTarget.scrollLeft;
    };
    const Box = multiline ? Textarea : Input;
    return (
      <div className="relative">
        <div
          ref={backdrop}
          aria-hidden="true"
          data-template-backdrop
          className={cn(
            "pointer-events-none absolute inset-0 overflow-hidden rounded-lg border-[1.5px] border-transparent px-3",
            multiline
              ? // A box several lines tall reserves its scrollbar's room; the copy the same.
                "[scrollbar-gutter:stable] py-2 text-sm break-words whitespace-pre-wrap"
              : "flex items-center py-1 text-base whitespace-pre md:text-sm",
            disabled && "opacity-50",
          )}
        >
          <span>
            {templateSegments(value).map((segment, index) =>
              segment.placeholder ? (
                <Placeholder
                  key={index}
                  text={segment.text}
                  stepNames={stepNames}
                  unknown={segment.text === unknown}
                />
              ) : (
                <span key={index}>{segment.text}</span>
              ),
            )}
            {/* A last empty line still takes its height, as it does in the box. */}
            {multiline && value.endsWith("\n") && " "}
          </span>
        </div>
        <Box
          ref={(element: (HTMLInputElement & HTMLTextAreaElement) | null) => {
            own.current = element;
            if (typeof ref === "function") ref(element);
            else if (ref !== null) ref.current = element;
          }}
          id={id}
          rows={multiline ? 3 : undefined}
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          aria-invalid={invalid}
          className={cn(
            "selection:bg-primary/20 caret-foreground relative text-transparent",
            multiline && "[scrollbar-gutter:stable]",
          )}
          // A text box throughout, as a textarea must be: a role switched while
          // focused goes unannounced. It takes no aria-expanded, so the open list
          // is said through what it controls and the option it points at.
          aria-autocomplete="list"
          aria-controls={open ? listId : undefined}
          aria-activedescendant={open ? `${listId}-${shown}` : undefined}
          onChange={(event: { target: { value: string } }) => onChange(event.target.value)}
          onSelect={track}
          onKeyDown={keys}
          onBlur={(event: Parameters<FocusEventHandler>[0]) => {
            setCaret(null);
            onBlur(event);
          }}
          onScroll={follow}
        />
        {open && <SuggestionList id={listId} suggestions={matches} active={shown} onPick={pick} />}
      </div>
    );
  },
);

/**
 * One placeholder, coloured by part. Every part keeps the box's font and weight -
 * only colour changes - or the copy would stop lining up with the caret.
 */
function Placeholder({
  text,
  stepNames,
  unknown,
}: {
  text: string;
  stepNames: readonly string[];
  unknown: boolean;
}) {
  const inner = text.slice(2, -2);
  const lead = inner.length - inner.trimStart().length;
  const body = inner.trim();
  const trail = inner.length - lead - body.length;
  // The longest step name the placeholder starts with, as parsing reads it.
  const step =
    [...stepNames]
      .sort((a, b) => b.length - a.length)
      .find((name) => body === name || body.startsWith(`${name}.`)) ??
    (body.split(".")[0] as string);
  const path = body.slice(step.length);
  return (
    <span
      data-placeholder
      className={cn(
        "rounded-sm [box-decoration-break:clone]",
        unknown
          ? "bg-destructive/10 text-destructive decoration-destructive underline decoration-wavy"
          : "bg-[var(--domain-build-subtle)]",
      )}
    >
      <span className={unknown ? undefined : "text-muted-foreground"}>
        {`{{${inner.slice(0, lead)}`}
      </span>
      <span data-part="step" className={unknown ? undefined : "text-[var(--domain-build)]"}>
        {step}
      </span>
      <span data-part="path" className={unknown ? undefined : "text-[var(--domain-workspace)]"}>
        {path}
      </span>
      <span className={unknown ? undefined : "text-muted-foreground"}>
        {`${inner.slice(inner.length - trail)}}}`}
      </span>
    </span>
  );
}
