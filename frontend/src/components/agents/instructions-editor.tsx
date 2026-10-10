"use client";

import { useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { useTranslations } from "next-intl";

import { MarkdownEditor } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  insertVariable,
  matching,
  openVariable,
  type OpenVariable,
} from "@/lib/variable-completion";

export interface VariableOption {
  name: string;
  description: string;
}

interface InstructionsEditorProps {
  value: string;
  onChange: (next: string) => void;
  label: string;
  placeholder?: string;
  disabled?: boolean;
  /** Every variable the instructions may use, system and custom. */
  variables: VariableOption[];
  /** Lets the variables panel insert at the caret. */
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
}

/**
 * The agent's instructions, with `{{` completing a variable (#2065).
 *
 * Typing `{{` opens the list under the editor, filtered as the name is typed;
 * ↑/↓ move, Enter or Tab inserts, Escape closes. The list sits under the field
 * rather than at the caret: a textarea has no caret coordinates to anchor to, and
 * a list that jumps around a long prompt is harder to read than one that stays put.
 */
export function InstructionsEditor({
  value,
  onChange,
  label,
  placeholder,
  disabled,
  variables,
  textareaRef,
}: InstructionsEditorProps) {
  const t = useTranslations("agents");
  const ownRef = useRef<HTMLTextAreaElement>(null);
  const box = textareaRef ?? ownRef;
  const [caret, setCaret] = useState<number | null>(null);
  const [highlight, setHighlight] = useState(0);
  const [dismissed, setDismissed] = useState<number | null>(null);

  const open = caret === null ? null : openVariable(value, caret);
  const options = open && open.start !== dismissed ? matching(variables, open.query) : [];
  const showing = options.length > 0;
  const active = Math.min(highlight, Math.max(options.length - 1, 0));

  const change = (next: string, at: number) => {
    onChange(next);
    setCaret(at);
    setHighlight(0);
  };

  const choose = (name: string, around: OpenVariable) => {
    const inserted = insertVariable(value, around.end, around, name);
    onChange(inserted.text);
    setCaret(null);
    requestAnimationFrame(() => {
      box.current?.focus();
      box.current?.setSelectionRange(inserted.caret, inserted.caret);
    });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!showing) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setHighlight((active + step + options.length) % options.length);
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      choose(options[active]!.name, open!);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setDismissed(open!.start);
    }
  };

  return (
    <div className="relative">
      <MarkdownEditor
        textareaRef={box}
        label={label}
        value={value}
        onChange={change}
        onKeyDown={onKeyDown}
        rows={10}
        disabled={disabled}
        placeholder={placeholder}
      />
      {showing && (
        <ul
          role="listbox"
          aria-label={t("variablesSuggestions")}
          className="bg-popover border-border absolute inset-x-2 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-lg border p-1 shadow-lg"
        >
          {options.map((option, index) => (
            <li key={option.name} role="option" aria-selected={index === active}>
              <button
                type="button"
                // Keeps the focus, and with it the caret, in the textarea.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(option.name, open!)}
                className={cn(
                  "flex w-full items-baseline gap-3 rounded-md px-2 py-1.5 text-left",
                  index === active ? "bg-foreground/[0.06]" : "hover:bg-foreground/[0.03]",
                )}
              >
                <span className="font-mono text-xs">{`{{${option.name}}}`}</span>
                <span className="text-muted-foreground truncate text-xs">{option.description}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
